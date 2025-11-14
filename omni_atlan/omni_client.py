"""Omni API client for fetching metadata"""

import json
import requests
from typing import List, Dict, Optional, Any
from omni_atlan.config import OmniConfig


class OmniClient:
    """Client for interacting with Omni API"""
    
    def __init__(self, config: OmniConfig):
        self.config = config
        self.base_url = f"{config.base_url.rstrip('/')}/api"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}"
        }
        self._last_request_time = 0
        self._min_request_interval = 1.1  # Slightly more than 1 second to stay under 60/min
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make a request to the Omni API with rate limiting handling"""
        import time
        
        # Rate limiting: ensure we don't exceed 60 requests/minute
        current_time = time.time()
        time_since_last_request = current_time - self._last_request_time
        if time_since_last_request < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last_request
            time.sleep(sleep_time)
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        max_retries = 3
        retry_delay = 5  # Start with 5 seconds for rate limit retries
        
        for attempt in range(max_retries):
            try:
                response = requests.request(method, url, headers=self.headers, **kwargs)
                self._last_request_time = time.time()
                
                # Handle rate limiting (429)
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff: 5, 10, 20
                        print(f"⚠ Rate limited on {endpoint}. Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"❌ Rate limit exceeded after {max_retries} attempts for {endpoint}")
                        response.raise_for_status()
                
                response.raise_for_status()
                
                # Handle different response types
                try:
                    return response.json()
                except ValueError:
                    # If response is not JSON, return as text
                    return response.text
                    
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"⚠ Request failed: {e}. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise
    
    def _normalize_list_response(self, result: Any) -> List[Dict[str, Any]]:
        """Normalize API response to a list of dictionaries"""
        if isinstance(result, list):
            return [item if isinstance(item, dict) else {"id": str(item), "name": str(item)} for item in result]
        elif isinstance(result, dict):
            if "items" in result:
                items = result["items"]
                return [item if isinstance(item, dict) else {"id": str(item), "name": str(item)} for item in items] if isinstance(items, list) else []
            elif "data" in result:
                data = result["data"]
                if isinstance(data, list):
                    return [item if isinstance(item, dict) else {"id": str(item), "name": str(item)} for item in data]
                return [data] if isinstance(data, dict) else [{"id": str(data), "name": str(data)}]
        elif isinstance(result, str):
            # If it's a string, try to parse as JSON or return empty
            try:
                parsed = json.loads(result)
                return self._normalize_list_response(parsed)
            except:
                return []
        return []
    
    def get_topics(self, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch topics from Omni, optionally filtered by modelId
        
        Args:
            model_id: Optional model ID to filter topics
        
        Returns:
            List of topics
        """
        try:
            params = {}
            if model_id:
                params["modelId"] = model_id
            
            result = self._request("GET", "/v1/topics", params=params)
            return self._normalize_list_response(result)
        except Exception as e:
            print(f"Error fetching topics: {e}")
            return []
    
    def get_topic(self, topic_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a specific topic by ID"""
        try:
            return self._request("GET", f"/v1/topics/{topic_id}")
        except Exception as e:
            print(f"Error fetching topic {topic_id}: {e}")
            return None
    
    def get_queries(self, topic_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch queries, optionally filtered by topic"""
        try:
            endpoint = "/v1/queries"
            params = {}
            if topic_id:
                params["topic_id"] = topic_id
            result = self._request("GET", endpoint, params=params)
            return self._normalize_list_response(result)
        except Exception as e:
            print(f"Error fetching queries: {e}")
            return []
    
    def get_documents(self) -> List[Dict[str, Any]]:
        """
        Fetch all documents (dashboards/workbooks) from Omni with pagination
        
        Returns:
            List of documents
        """
        try:
            all_documents = []
            cursor = None
            
            while True:
                params = {}
                if cursor:
                    params["cursor"] = cursor
                
                result = self._request("GET", "/v1/documents", params=params)
                
                # Handle paginated response structure
                if isinstance(result, dict) and "records" in result:
                    records = result.get("records", [])
                    all_documents.extend(records)
                    
                    page_info = result.get("pageInfo", {})
                    if not page_info.get("hasNextPage", False):
                        break
                    cursor = page_info.get("nextCursor")
                else:
                    # Fallback to old structure
                    documents = self._normalize_list_response(result)
                    all_documents.extend(documents)
                    break
            
            return all_documents
        except Exception as e:
            print(f"Error fetching documents: {e}")
            return []
    
    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a specific document by ID"""
        try:
            return self._request("GET", f"/v1/documents/{document_id}")
        except Exception as e:
            print(f"Error fetching document {document_id}: {e}")
            return None
    
    def get_document_queries(self, document_identifier: str) -> List[Dict[str, Any]]:
        """
        Fetch queries for a specific document
        
        Args:
            document_identifier: Document identifier (not ID)
        
        Returns:
            List of queries (includes fields used)
        """
        try:
            result = self._request("GET", f"/v1/documents/{document_identifier}/queries")
            # Response structure: {"queries": [...]}
            if isinstance(result, dict) and "queries" in result:
                return result["queries"]
            # Fallback to normalize if structure is different
            return self._normalize_list_response(result)
        except Exception as e:
            print(f"Error fetching queries for document {document_identifier}: {e}")
            return []
    
    def get_connections(self) -> List[Dict[str, Any]]:
        """Fetch all connections from Omni"""
        try:
            result = self._request("GET", "/v1/connections")
            # Response structure: {"connections": [...]}
            if isinstance(result, dict) and "connections" in result:
                return result["connections"]
            # Fallback to normalize if structure is different
            return self._normalize_list_response(result)
        except Exception as e:
            print(f"Error fetching connections: {e}")
            return []
    
    def get_models(self, include_branches: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch all models from Omni (paginated)
        
        Args:
            include_branches: If True, includes active branches in response
        
        Returns:
            List of model records
        """
        try:
            params = {}
            if include_branches:
                params["include"] = "activeBranches"
            
            all_models = []
            cursor = None
            
            while True:
                if cursor:
                    params["cursor"] = cursor
                
                result = self._request("GET", "/v1/models", params=params)
                
                # Handle paginated response
                if isinstance(result, dict) and "records" in result:
                    all_models.extend(result["records"])
                    page_info = result.get("pageInfo", {})
                    if not page_info.get("hasNextPage", False):
                        break
                    cursor = page_info.get("nextCursor")
                else:
                    # Non-paginated response
                    all_models = self._normalize_list_response(result)
                    break
            
            return all_models
        except Exception as e:
            print(f"Error fetching models: {e}")
            return []
    
    def get_models_by_kind(self, model_kind: str, include_branches: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch models filtered by modelKind (SCHEMA, SHARED, WORKBOOK)
        
        Args:
            model_kind: Type of model (SCHEMA, SHARED, WORKBOOK)
            include_branches: If True, includes active branches
        
        Returns:
            List of models matching the modelKind
        """
        all_models = self.get_models(include_branches=include_branches)
        return [model for model in all_models if model.get("modelKind") == model_kind]
    
    def get_schema_models(self) -> List[Dict[str, Any]]:
        """Fetch schema models (modelKind: SCHEMA)"""
        return self.get_models_by_kind("SCHEMA")
    
    def get_shared_models(self, include_branches: bool = True) -> List[Dict[str, Any]]:
        """Fetch shared models (modelKind: SHARED)"""
        return self.get_models_by_kind("SHARED", include_branches=include_branches)
    
    def get_workbook_models(self) -> List[Dict[str, Any]]:
        """Fetch workbook models (modelKind: WORKBOOK)"""
        return self.get_models_by_kind("WORKBOOK")
    
    def execute_query(self, query_id: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a query in Omni"""
        try:
            endpoint = f"/v1/queries/{query_id}/execute"
            payload = parameters or {}
            return self._request("POST", endpoint, json=payload)
        except Exception as e:
            print(f"Error executing query {query_id}: {e}")
            return {}
    

