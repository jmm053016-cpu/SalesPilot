"""
Agent 回调处理器
采集 Agent 调用过程中的回调事件，供界面安全呈现。
继承 BaseCallbackHandler，在 Streamlit 中实时显示工具调用和 LLM token 流式输出

架构说明：
- on_tool_start: 在侧边栏显示工具调用开始
- on_tool_end:   更新侧边栏显示工具调用完成
- on_llm_new_token: 在主区域实时流式输出 LLM 回复 token
- 所有工具调用记录追加到 st.session_state.tool_history
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

import streamlit as st
from langchain_core.callbacks import BaseCallbackHandler


class StreamlitCallbackHandler(BaseCallbackHandler):
    """
    Streamlit 专用回调处理器，实现：
    1. 侧边栏实时显示工具调用状态（st.info / st.success）
    2. 工具调用历史持久化到 st.session_state
    3. LLM token 级流式输出到聊天区域
    """

    def __init__(self, sidebar_container, response_placeholder):
        """
        参数:
          - sidebar_container: 侧边栏中的 st.empty() 容器，用于实时刷新工具调用状态
          - response_placeholder: 聊天区域的 st.empty() 容器，用于流式输出 LLM 回复
        """
        super().__init__()
        self.sidebar_container = sidebar_container  # 侧边栏实时状态容器
        self.response_placeholder = response_placeholder  # 主区域流式回复容器
        self.streaming_text = ""  # 累积的流式文本

    # ---- 工具调用回调 ----

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """工具开始调用时触发：在侧边栏显示调用信息"""
        tool_name = serialized.get("name", "unknown_tool")

        # 格式化参数（截断过长的参数）
        params_display = input_str
        if len(params_display) > 200:
            params_display = params_display[:200] + "..."

        # 追加到历史记录
        if "tool_history" not in st.session_state:
            st.session_state.tool_history = []
        st.session_state.tool_history.append({
            "tool": tool_name,
            "input": input_str,
            "output": "",
            "time": datetime.now().strftime("%H:%M:%S"),
            "status": "running",
        })

        # 在侧边栏显示调用状态
        with self.sidebar_container.container():
            st.info(f"🔧 调用工具: **{tool_name}**\n\n参数: `{params_display}`")

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """工具调用完成时触发：更新侧边栏和历史状态"""
        # 更新最后一条历史记录的状态
        if st.session_state.get("tool_history"):
            last = st.session_state.tool_history[-1]
            last["output"] = output[:300] if len(str(output)) > 300 else str(output)
            last["status"] = "done"

        # 截断输出用于展示
        output_display = str(output)
        if len(output_display) > 200:
            output_display = output_display[:200] + "..."

        with self.sidebar_container.container():
            st.success(f"✅ 工具返回结果，Agent 继续思考")

    # ---- LLM token 流式输出回调 ----

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """LLM 每生成一个 token 时触发，实现流式输出"""
        self.streaming_text += token
        self.response_placeholder.markdown(self.streaming_text)

    # ---- 错误处理 ----

    def on_tool_error(self, error: Exception, **kwargs: Any) -> None:
        """工具调用出错时触发"""
        if st.session_state.get("tool_history"):
            last = st.session_state.tool_history[-1]
            last["status"] = "error"
            last["output"] = str(error)
        with self.sidebar_container.container():
            st.error(f"❌ 工具调用出错: {str(error)[:200]}")

    def get_streaming_text(self) -> str:
        """获取累积的流式文本"""
        return self.streaming_text
