import asyncio
from datetime import datetime
from types import AsyncGeneratorType

from sqlalchemy import (
    Integer, String, DateTime, ForeignKey, func, select
    )
from sqlalchemy.ext.asyncio import (
    AsyncSession, create_async_engine, async_sessionmaker
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship
)

DATABASE_URL = 'sqlite+aiosqlite:///./database.db/'
engine = create_async_engine(DATABASE_URL, echo=False)

async_session_maker = async_sessionmaker(engine, 
                                         class_=AsyncSession,
                                         expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, 
                                             unique=True,
                                             index=True)
    joined_date: Mapped[datetime] = mapped_column(DateTime,
                                            server_default=func.now())
    
    words = relationship("VocabularyWord", back_populates="user",
                         cascade="all, delete-orphan")

class VocabularyWord(Base):
    __tablename__ = 'vocabulary_words'

    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)  
    user_id: Mapped[int] = mapped_column(Integer, 
                                         ForeignKey("users.id",
                                                    ondelete="CASCADE"),
                                        index=True)
    original_text: Mapped[str] = mapped_column(String, nullable=False)
    translate_text: Mapped[str] = mapped_column(String, nullable=False)
    source_lang: Mapped[str] = mapped_column(String, nullable=False)
    target_lang: Mapped[str] = mapped_column(String, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime,
                                        server_default=func.now())
    
    user = relationship("User", back_populates="words")



async def get_user_words(telegram_id:int, offset:int=0, limit:int=5):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id==telegram_id))
        user = result.scalar_one_or_none()

        if not user:
            return [] 
        
        result = await session.execute(
            select(VocabularyWord)
            .where(VocabularyWord.user_id == user.id)
            .order_by(VocabularyWord.added_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()
    

async def get_user_words_count(telegram_id:int):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id==telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return 0
        
        result = await session.execute(
            select(func.count(
                VocabularyWord.id
            )).where(
                VocabularyWord.user_id==user.id
            )
        )
        return result.scalar()


class TestResult(Base): 

    __tablename__ = 'test_results'

    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer,
                                         ForeignKey('users.id'))
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer,
                                                 nullable=False)
    test_date: Mapped[datetime] = mapped_column(DateTime,
                                    server_default=func.now())
    
    user = relationship('User')

async def save_results(telegram_id, score, total_questions):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id==telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=telegram_id)
            session.add(user)
            await session.flush()

        test_result = TestResult(
            user_id=user.id,
            score=score,
            total_questions=total_questions
        )
        session.add(test_result)
        await session.commit()

# получение результатов
async def get_test_result(telegram_id):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id==telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return 0, 0
        
        count_result = await session.execute(
            select(func.count(TestResult.id)).where(TestResult.user_id==user.id)
        )
        test_count = count_result.scalar()
        if test_count == 0:
            return 0, 0
        
        stats_result = await session.execute(
            select(TestResult.score, TestResult.total_questions).where(TestResult.user_id==user.id)
        )
        results = stats_result.scalar.all()
        total_percentage = sum((r.score/r.total_questions)*100 for r in results)

        return test_count, total_percentage




async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('база создана')

# генератор ассинхронной сессии
async def get_async_session():
    async with async_session_maker() as session:
        yield session

