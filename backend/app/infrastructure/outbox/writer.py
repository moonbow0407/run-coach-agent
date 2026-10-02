"""Session-bound Outbox writer；调用方拥有 canonical transaction。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.events import DurableEventEnvelope
from app.common.ids import new_id
from app.infrastructure.database.models.outbox import OutboxEventRow


class OutboxWriter:
    """只把 event 加入给定 Session，绝不自行提交或打开第二个事务。"""

    def add(self, session: AsyncSession, event: DurableEventEnvelope) -> None:
        session.add(
            OutboxEventRow(
                id=new_id(),
                event_id=event.event_id,
                event_type=event.event_type,
                schema_version=event.schema_version,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                user_id=event.user_id,
                occurred_at=event.occurred_at,
                payload=event.payload,
                correlation_id=event.metadata.correlation_id,
                causation_id=event.metadata.causation_id,
                trace_id=event.metadata.trace_id,
                status="pending",
                available_at=event.occurred_at,
                claimed_by=None,
                claim_until=None,
                publish_attempt_count=0,
                last_error_code=None,
                created_at=event.occurred_at,
                published_at=None,
                quarantined_at=None,
            )
        )
