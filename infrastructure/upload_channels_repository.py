from typing import List, Optional
from sqlmodel import Session, select
from core.db import engine, UploadChannelModel
from domain.upload_channels import (
    UploadChannelRecord,
    UploadChannelCreateCommand,
    UploadChannelUpdateCommand,
)


class UploadChannelsRepository:
    def _to_record(self, model: UploadChannelModel) -> UploadChannelRecord:
        return UploadChannelRecord(
            id=model.id,
            name=model.name,
            channel_type=model.channel_type,
            api_url=model.api_url,
            api_key=model.api_key,
            is_enabled=model.is_enabled,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def list_all(self, enabled_only: bool = False) -> List[UploadChannelRecord]:
        with Session(engine) as session:
            query = select(UploadChannelModel)
            if enabled_only:
                query = query.where(UploadChannelModel.is_enabled == True)
            models = session.exec(query).all()
            return [self._to_record(m) for m in models]

    def get_by_id(self, channel_id: int) -> Optional[UploadChannelRecord]:
        with Session(engine) as session:
            model = session.get(UploadChannelModel, channel_id)
            if model:
                return self._to_record(model)
            return None

    def create(self, cmd: UploadChannelCreateCommand) -> UploadChannelRecord:
        with Session(engine) as session:
            model = UploadChannelModel(
                name=cmd.name,
                channel_type=cmd.channel_type,
                api_url=cmd.api_url,
                api_key=cmd.api_key,
                is_enabled=cmd.is_enabled,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            return self._to_record(model)

    def update(self, channel_id: int, cmd: UploadChannelUpdateCommand) -> Optional[UploadChannelRecord]:
        with Session(engine) as session:
            model = session.get(UploadChannelModel, channel_id)
            if not model:
                return None

            if cmd.name is not None:
                model.name = cmd.name
            if cmd.channel_type is not None:
                model.channel_type = cmd.channel_type
            if cmd.api_url is not None:
                model.api_url = cmd.api_url
            if cmd.api_key is not None:
                model.api_key = cmd.api_key
            if cmd.is_enabled is not None:
                model.is_enabled = cmd.is_enabled

            session.add(model)
            session.commit()
            session.refresh(model)
            return self._to_record(model)

    def delete(self, channel_id: int) -> bool:
        with Session(engine) as session:
            model = session.get(UploadChannelModel, channel_id)
            if not model:
                return False
            session.delete(model)
            session.commit()
            return True
