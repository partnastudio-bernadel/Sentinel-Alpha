import os
import re
from bson.json_util import loads, dumps
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.tools import create_retriever_tool
from functions.utils.db.connect import get_db_client, get_vector_collection

def execute_mql(client, db_name, query_str):
    query_str = query_str.strip()
    pattern = r'^db(?:\["([^"]+)"\]|\.(\w+))\.aggregate\((.*)\)$'
    match = re.match(pattern, query_str, re.DOTALL)
    if not match:
        return f"Error: Query must be of the form db.collectionName.aggregate([...])"
    
    collection_name = match.group(1) or match.group(2)
    pipeline_str = match.group(3).strip()
    
    try:
        pipeline = loads(pipeline_str)
        db = client[db_name]
        collection = db[collection_name]
        results = list(collection.aggregate(pipeline))
        return dumps(results)
    except Exception as e:
        return f"Error executing query: {e}"

class MockQueryTool:
    def __init__(self, client, db_name):
        self.client = client
        self.db_name = db_name
        self.name = "query_mongodb"
        self.description = "Executes a MongoDB MQL query against historical databases and returns the results."

    def invoke(self, input_dict):
        query = input_dict.get("query")
        return execute_mql(self.client, self.db_name, query)

class MockToolkit:
    def __init__(self, client, db_name):
        self.tool = MockQueryTool(client, db_name)

    def get_tools(self):
        return [self.tool]

def get_mongodb_toolkit(llm):
    """Initializes and returns the MongoDBDatabaseToolkit for agents to query historical sentiment data."""
    db_name = os.getenv("MONGODB_DB", "sentinel_db")
    
    # Use centralized connection and instantiate MockToolkit directly
    client, _ = get_db_client()
    return MockToolkit(client=client, db_name=db_name)

def get_mongodb_retriever_tool(embeddings):
    """Creates a LangChain retriever tool wrapping MongoDBAtlasVectorSearch for calibration query RAG."""
    index_name = os.getenv("MONGODB_VECTOR_INDEX", "vector_index")
    
    # Use centralized vector collection helper
    collection = get_vector_collection()
    
    vector_store = MongoDBAtlasVectorSearch(
        collection=collection,
        embedding=embeddings,
        index_name=index_name,
        text_key="text",
        embedding_key="embedding"
    )
    
    retriever = vector_store.as_retriever(search_kwargs={"k": 2})
    
    retriever_tool = create_retriever_tool(
        retriever,
        name="retrieve_calibration_examples",
        description="Search for similar financial sentence calibration examples and their corresponding sentiment classifications."
    )
    return retriever_tool
