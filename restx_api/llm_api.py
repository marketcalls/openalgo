# restx_api/llm_api.py
"""LLM API endpoints for AI commentary."""

from flask_restx import Namespace, Resource

from limiter import limiter
from services.llm_service import generate_commentary
from utils.logging import get_logger

api = Namespace("llm", description="LLM AI Commentary Endpoints")
logger = get_logger(__name__)


@api.route("/commentary")
class CommentaryResource(Resource):
    @limiter.limit("5 per second")
    def post(self):
        """Generate AI commentary for analysis data."""
        from flask import request

        data = request.get_json(force=True)

        api_key = data.get("apikey", "")
        if not api_key:
            return {"status": "error", "message": "apikey required"}, 400

        analysis = data.get("analysis", {})
        if not analysis:
            return {"status": "error", "message": "analysis data required"}, 400

        result = generate_commentary(analysis)

        if not result.success:
            return {"status": "error", "message": result.error or "LLM unavailable"}

        return {
            "status": "success",
            "data": {
                "commentary": result.text,
                "provider": result.provider,
                "model": result.model,
            },
        }


@api.route("/models")
class ModelsResource(Resource):
    def get(self):
        """List available LLM models."""
        from ai.model_registry import ModelType, get_registry

        registry = get_registry()
        models = [
            {"id": m.id, "name": m.name, "provider": m.provider, "type": m.type.value, "enabled": m.enabled}
            for m in registry.list_all()
        ]
        return {"status": "success", "data": models}
