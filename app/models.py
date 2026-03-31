import uuid
from datetime import datetime, UTC
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    working_dir: Mapped[str | None] = mapped_column(String(512), nullable=True)
    opencode_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="channel", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    channel_id: Mapped[str] = mapped_column(String(36), ForeignKey("channels.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    channel: Mapped["Channel"] = relationship("Channel", back_populates="messages")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    minute: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    days_of_week: Mapped[str] = mapped_column(String(255), nullable=False, default="mon,tue,wed,thu,fri")
    working_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    email_to: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    runs: Mapped[list["TaskRun"]] = relationship(
        "TaskRun", back_populates="task", cascade="all, delete-orphan"
    )


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | success | error
    output: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="runs")
