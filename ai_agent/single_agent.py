from . import tools

from zoneinfo import ZoneInfo
from datetime import datetime
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langchain_core.messages import SystemMessage, ToolMessage, HumanMessage, AIMessage
from langfuse.langchain import CallbackHandler
import os


def read_text_file(file_path: str) -> str:
    with open(file_path, "r") as file:
        return file.read()


def get_current_time() -> str:
    """
    Get the current time formatted nicely for display.
    """
    # Get current datetime
    now = datetime.now(ZoneInfo("Europe/Zurich"))
    formatted = now.strftime("%A, %B %d, %Y at %H:%M")
    return f"It is currently {formatted}."


class State(TypedDict):
    messages: Annotated[list, add_messages]


class ToolMessageFilteringMemory(InMemorySaver):
    def save_state(self, agent_config, state):
        # Remove ToolMessages before actually saving
        cleaned_state = state.copy()
        cleaned_state["messages"] = [
            m
            for m in cleaned_state.get("messages", [])
            if not isinstance(m, ToolMessage)
        ]
        super().save_state(agent_config, cleaned_state)


class OpenBISAgent:
    """
    An agent that can answer questions about openBIS inventories.
    It uses a LangChain model and tools to interact with the openBIS session.
    """

    def __init__(self):
        self.messages = {"messages": []}

        if os.environ["LLM_PROVIDER"] == "OpenAI":
            self.llm_api_key = os.environ["LLM_API_KEY"]
            self.llm_model = ChatOpenAI(
                model=os.environ["LLM_MODEL"],
                openai_api_key=self.llm_api_key,
                temperature=0.5,
                max_retries=3,
            )
        elif os.environ["LLM_PROVIDER"] == "Google Gemini":
            self.llm_api_key = os.environ["LLM_API_KEY"]
            self.llm_model = ChatGoogleGenerativeAI(
                model=os.environ["LLM_MODEL"],
                google_api_key=self.llm_api_key,
                temperature=0.5,
                max_retries=3,
            )

        self.system_prompt = read_text_file("ai_agent/data/system_prompt.txt")
        self.system_prompt += f"\nToday is {get_current_time()}."

        self._tools = [
            # General openBIS objects tools
            tools.get_openbis_objects,
            tools.get_openbis_object_by_permId,
            tools.get_openbis_objects_by_name,
            tools.get_openbis_objects_by_date,
            # Inventory
            tools.get_live_samples_by_properties,
            tools.get_substances_by_properties,
            tools.get_crystals_by_properties,
            tools.get_2d_materials_by_properties,
            tools.get_reacprods_by_properties,
            # Simulations
            tools.get_simulations_by_molecule,
            tools.get_simulations_by_crystal_concept,
            tools.get_simulations_by_reacprod_concept,
            tools.import_simulation_from_openbis,
            # Experiments
            tools.get_samples_by_substance,
            tools.get_samples_by_crystal,
            tools.get_measurements_by_sample,
            # RAG
            tools.get_processes_documents,
        ]

        llm_with_tools = self.llm_model.bind_tools(self._tools)

        def chatbot(state: State):
            # Inject the system prompt at the start (only once)
            messages = state["messages"]

            # Check if the system prompt is already there to avoid duplication
            if not any(
                isinstance(msg, SystemMessage) and msg.content == self.system_prompt
                for msg in messages
            ):
                messages = [SystemMessage(content=self.system_prompt)] + messages

            return {"messages": [llm_with_tools.invoke(messages)]}

        tool_node = ToolNode(tools=self._tools)

        # Define the state machine
        # Add the nodes
        graph_builder = StateGraph(State)
        graph_builder.add_node("chatbot", chatbot)
        graph_builder.add_node("tools", tool_node)

        # Build the edges
        graph_builder.add_edge(START, "chatbot")
        graph_builder.add_conditional_edges("chatbot", tools_condition)
        graph_builder.add_edge("tools", "chatbot")

        self.graph = graph_builder.compile()

        # memory = InMemorySaver()
        # self.graph = graph_builder.compile(checkpointer=memory)
        # self.agent_config = {"configurable": {"thread_id": uuid4()}}

    def ask_question(self, user_prompt: str):
        """
        Ask a question to the agent and get a response.

        Args:
            user_prompt (str): The question to ask the agent.

        Returns:
            str: The response from the agent.
        """
        # Builds a LangGraph agent that interleaves reasoning and tool execution (ReAct pattern)
        # Runs the full workflow, returning a state object
        # where the last message contains the model’s response after any tool invocations
        self.messages["messages"].append({"role": "user", "content": user_prompt})

        events = self.graph.stream(
            self.messages,
            stream_mode="values",
            config={"callbacks": [CallbackHandler()]},
        )

        response = []
        for event in events:
            role = ""

            if isinstance(event["messages"][-1], HumanMessage):
                role = "user"
            elif isinstance(event["messages"][-1], AIMessage):
                role = "assistant"
            elif isinstance(event["messages"][-1], SystemMessage):
                role = "system"

            if role:
                message = {"role": role, "content": event["messages"][-1].content}
                if message not in self.messages["messages"]:
                    self.messages["messages"].append(message)

            response.append(event["messages"][-1])

        return response

    def get_graph_replay(self):
        to_replay = None
        for state in self.graph.get_state_history(self.agent_config):
            print("Num Messages: ", len(state.values["messages"]), "Next: ", state.next)
            print("-" * 80)
            if len(state.values["messages"]) == 10:
                # We are somewhat arbitrarily selecting a specific state based on the number of chat messages in the state.
                to_replay = state

        return to_replay
