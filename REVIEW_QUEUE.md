# OpenAlgo Review Queue

This queue tracks source-backed ambiguities, mismatches, and review items found during discovery. It does not describe planned behavior.

## Open Items

1. Historify environment name mismatch.
   - Evidence: `.sample.env:61` documents `HISTORIFY_DATABASE_URL`; `database/historify_db.py:27` reads `HISTORIFY_DATABASE_PATH`.
   - Review question: Should the sample env change, should the implementation accept both, or is one name intentionally deprecated?

2. Analyzer-mode GTT tables exist, but GTT services return 501.
   - Evidence: sandbox GTT models are defined at `database/sandbox_db.py:265`; place, modify, cancel, and orderbook services return analyzer unsupported at `services/place_gtt_order_service.py:54`, `services/modify_gtt_order_service.py:51`, `services/cancel_gtt_order_service.py:50`, and `services/gtt_orderbook_service.py:21`.
   - Review question: Is sandbox GTT intentionally reserved for future work or is service implementation missing?

3. Broker count in current code differs from old broker integration guide.
   - Evidence: `.sample.env:22` lists 33 brokers; `docs/broker-integration-guide.md:1443` says 29 brokers.
   - Review question: Should the old guide be updated or replaced by generated broker plugin inventory?

4. Live GTT support is narrower than the general broker plugin list.
   - Evidence: GTT services dynamically import `broker.{broker}.api.gtt_api` at `services/place_gtt_order_service.py:34`; live GTT modules were found only at `broker/dhan/api/gtt_api.py:1` and `broker/zerodha/api/gtt_api.py:1`.
   - Review question: Should user docs state GTT as Dhan/Zerodha-only unless broker modules are added?

5. Remote MCP endpoints are present in source but conditional at runtime.
   - Evidence: app registers MCP routes only when `MCP_HTTP_ENABLED=True` at `app.py:303`; debug mode is refused and `MCP_PUBLIC_URL` is required at `app.py:303`.
   - Review question: Should endpoint inventories separate unconditional Flask routes from runtime-enabled routes?

6. React route precedence depends on build artifact presence.
   - Evidence: React routes register first only when `frontend/dist` exists at `app.py:236`; legacy routes such as `/dashboard` still exist at `blueprints/dashboard.py:17`.
   - Review question: Should docs document production route precedence separately from source route inventory?

7. Semi-auto behavior is split between central routing and service-level blocks.
   - Evidence: queueable types are defined in `services/order_router_service.py:13`; order routing queues in semi-auto mode at `services/order_router_service.py:37`; close, cancel, cancel-all, modify, modify-GTT, and cancel-GTT block in their own services at `services/close_position_service.py:216`, `services/cancel_order_service.py:213`, `services/cancel_all_order_service.py:196`, `services/modify_order_service.py:208`, `services/modify_gtt_order_service.py:124`, and `services/cancel_gtt_order_service.py:132`.
   - Review question: Should documentation present this as a matrix per action and analyzer mode?

8. Broker response contracts are dynamic and not uniformly documented.
   - Evidence: broker modules are loaded dynamically at `utils/plugin_loader.py:65`; order placement expects status fields and broker order identifiers at `services/place_order_service.py:183`.
   - Review question: Should broker response schemas be audited per broker before publishing integration docs?
