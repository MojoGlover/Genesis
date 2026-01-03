"""
LangChain Agent
Automatically selects and uses tools
"""
from langchain_core.tools import Tool
from langchain_ollama import ChatOllama
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from core.tools.web_search import search_and_summarize
from core.tools.file_ops import read_file, write_file, list_files


# Define tools with descriptions
tools = [
    Tool(
        name="WebSearch",
        func=lambda query: search_and_summarize(query, max_results=3),
        description="Search the internet for current information. Use when you need recent data, news, or facts you don't know."
    ),
    Tool(
        name="ReadFile",
        func=read_file,
        description="Read content from a file. Input should be the filepath."
    ),
    Tool(
        name="ListFiles",
        func=list_files,
        description="List all files in the uploads directory."
    )
]


def create_agent_executor():
    """Create and return agent executor"""
    llm = ChatOllama(model="llama3.1:70b", base_url="http://localhost:11434")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful AI assistant. Use tools when necessary."),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])
    
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)


async def run_agent(query: str) -> str:
    """Run agent with query"""
    executor = create_agent_executor()
    result = executor.invoke({"input": query})
    return result["output"]
