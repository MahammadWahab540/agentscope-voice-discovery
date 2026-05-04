import asyncio
from typing import Awaitable, Callable, Dict, Optional
from agentscope.agent import RealtimeAgent
from agentscope import logger

AgentFactory = Callable[[], Awaitable[RealtimeAgent]]

class AgentPool:
    def __init__(self):
        self.pool: asyncio.Queue[RealtimeAgent] = asyncio.Queue()
        self.active_agents: Dict[str, RealtimeAgent] = {}
        self.target_size = 0
        self.factory_func: Optional[AgentFactory] = None
        self._fill_lock = asyncio.Lock()

    async def fill(self, factory_func: AgentFactory, count: int):
        """Pre-warm the pool with a number of agents."""
        self.factory_func = factory_func
        self.target_size = max(self.target_size, count)
        async with self._fill_lock:
            while self.pool.qsize() < count:
                try:
                    agent = await factory_func()
                    await self.pool.put(agent)
                except Exception as exc:
                    logger.error(f"Failed to pre-warm voice agent: {exc}")
                    break
        logger.info(f"Agent pool filled. Warm={self.pool.qsize()} active={len(self.active_agents)} target={self.target_size}")

    async def acquire(self, session_id: str, timeout: float = 0.25) -> Optional[RealtimeAgent]:
        """Acquire an agent from the pool for a specific session."""
        try:
            agent = await asyncio.wait_for(self.pool.get(), timeout=timeout)
            self.active_agents[session_id] = agent
            logger.info(f"Acquired agent for session {session_id}. Remaining in pool: {self.pool.qsize()}")
            return agent
        except asyncio.TimeoutError:
            logger.warning(f"Agent pool exhausted for session {session_id}; using cold fallback")
            return None
        except Exception as e:
            logger.error(f"Failed to acquire agent: {e}")
            return None

    async def discard(self, session_id: str):
        """Discard an assigned agent and replenish the warm pool."""
        agent = self.active_agents.pop(session_id, None)
        if agent:
            try:
                await agent.stop()
            except Exception as exc:
                logger.warning(f"Failed to stop pooled agent for session {session_id}: {exc}")
        self.replenish()

    def replenish(self):
        if self.factory_func and self.target_size:
            asyncio.create_task(self.fill(self.factory_func, self.target_size))

    def stats(self) -> dict:
        return {
            "warm": self.pool.qsize(),
            "active": len(self.active_agents),
            "target": self.target_size,
        }

agent_pool = AgentPool()
