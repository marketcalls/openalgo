# Production Readiness Checklist

- Historical data quality checks pass.
- Feature schema is versioned and frozen.
- Holdout validation is positive after cost assumptions.
- Walk-forward validation is stable.
- Paper-trade recommendations are logging correctly.
- Paper-trade feedback ingestion is working.
- Candidate versus active comparison report is generated daily.
- Manual approval workflow is in place.
- Rollback path to the previous active model is tested.
- Live system only performs inference, not retraining.
