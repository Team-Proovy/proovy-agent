"""VideoNode 스텁."""

from langchain_core.messages import AIMessage

from proovy_agent.graph.state import CreditEntry, ProovyState


async def video_node(state: ProovyState) -> dict:
    plan = [s.model_copy() for s in state.plan]
    if plan and state.executing_step_idx < len(plan):
        plan[state.executing_step_idx] = plan[state.executing_step_idx].model_copy(
            update={"status": "done"}
        )

    return {
        "messages": [
            AIMessage("해설 영상 생성 기능은 준비 중입니다.", metadata={"display": "content"})
        ],
        "credit_log": [CreditEntry(node="video_node", action="video", cost=0.0)],
        "plan": plan,
    }
