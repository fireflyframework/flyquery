# flyquery_sdk.AgentTablesApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_schema_object**](AgentTablesApi.md#get_schema_object) | **GET** /api/v1/agent/schema-objects/{object_id} | 
[**get_table**](AgentTablesApi.md#get_table) | **GET** /api/v1/agent/tables/{table_id} | 
[**get_table_by_name**](AgentTablesApi.md#get_table_by_name) | **GET** /api/v1/agent/tables/by-name/{name} | 
[**list_changes**](AgentTablesApi.md#list_changes) | **GET** /api/v1/agent/tables/{table_id}/changes | 
[**list_objects**](AgentTablesApi.md#list_objects) | **GET** /api/v1/agent/tables/{table_id}/objects | 
[**list_snapshots**](AgentTablesApi.md#list_snapshots) | **GET** /api/v1/agent/tables/{table_id}/snapshots | 
[**list_tables**](AgentTablesApi.md#list_tables) | **GET** /api/v1/agent/datasets/{dataset_id}/tables | 
[**search_tables**](AgentTablesApi.md#search_tables) | **GET** /api/v1/agent/tables | 


# **get_schema_object**
> SchemaObjectRead get_schema_object(object_id, x_agent_token, x_correlation_id=x_correlation_id)

### Example

* Api Key Authentication (AgentToken):

```python
import flyquery_sdk
from flyquery_sdk.models.schema_object_read import SchemaObjectRead
from flyquery_sdk.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = flyquery_sdk.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: AgentToken
configuration.api_key['AgentToken'] = os.environ["API_KEY"]

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['AgentToken'] = 'Bearer'

# Enter a context with an instance of the API client
async with flyquery_sdk.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = flyquery_sdk.AgentTablesApi(api_client)
    object_id = 'object_id_example' # str | 
    x_agent_token = 'fqt_live_aBcDeF1234567890aBcDeF1234567890' # str | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
    x_correlation_id = UUID('550e8400-e29b-41d4-a716-446655440000') # UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. (optional)

    try:
        api_response = await api_instance.get_schema_object(object_id, x_agent_token, x_correlation_id=x_correlation_id)
        print("The response of AgentTablesApi->get_schema_object:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentTablesApi->get_schema_object: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **object_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**SchemaObjectRead**](SchemaObjectRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **get_table**
> TableRead get_table(table_id, x_agent_token, x_correlation_id=x_correlation_id)

### Example

* Api Key Authentication (AgentToken):

```python
import flyquery_sdk
from flyquery_sdk.models.table_read import TableRead
from flyquery_sdk.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = flyquery_sdk.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: AgentToken
configuration.api_key['AgentToken'] = os.environ["API_KEY"]

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['AgentToken'] = 'Bearer'

# Enter a context with an instance of the API client
async with flyquery_sdk.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = flyquery_sdk.AgentTablesApi(api_client)
    table_id = 'table_id_example' # str | 
    x_agent_token = 'fqt_live_aBcDeF1234567890aBcDeF1234567890' # str | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
    x_correlation_id = UUID('550e8400-e29b-41d4-a716-446655440000') # UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. (optional)

    try:
        api_response = await api_instance.get_table(table_id, x_agent_token, x_correlation_id=x_correlation_id)
        print("The response of AgentTablesApi->get_table:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentTablesApi->get_table: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **table_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**TableRead**](TableRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **get_table_by_name**
> TableRead get_table_by_name(name, x_agent_token, dataset_id=dataset_id, x_correlation_id=x_correlation_id)

### Example

* Api Key Authentication (AgentToken):

```python
import flyquery_sdk
from flyquery_sdk.models.table_read import TableRead
from flyquery_sdk.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = flyquery_sdk.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: AgentToken
configuration.api_key['AgentToken'] = os.environ["API_KEY"]

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['AgentToken'] = 'Bearer'

# Enter a context with an instance of the API client
async with flyquery_sdk.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = flyquery_sdk.AgentTablesApi(api_client)
    name = 'name_example' # str | 
    x_agent_token = 'fqt_live_aBcDeF1234567890aBcDeF1234567890' # str | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
    dataset_id = 'dataset_id_example' # str |  (optional)
    x_correlation_id = UUID('550e8400-e29b-41d4-a716-446655440000') # UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. (optional)

    try:
        api_response = await api_instance.get_table_by_name(name, x_agent_token, dataset_id=dataset_id, x_correlation_id=x_correlation_id)
        print("The response of AgentTablesApi->get_table_by_name:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentTablesApi->get_table_by_name: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **name** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **dataset_id** | **str**|  | [optional] 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**TableRead**](TableRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **list_changes**
> PaginatedSchemaChangeRead list_changes(table_id, x_agent_token, x_correlation_id=x_correlation_id)

### Example

* Api Key Authentication (AgentToken):

```python
import asyncio
import os

from flyquery_sdk import ApiClient, Configuration
from flyquery_sdk.api import AgentTablesApi
from flyquery_sdk.exceptions import ApiException
from flyquery_sdk.models import PaginatedSchemaChangeRead


async def main():
    async with ApiClient(Configuration(host=os.environ["FLYQUERY_URL"])) as client:
        client.default_headers.update({
            "X-Tenant-Id": os.environ["FLYQUERY_TENANT_ID"],
            "X-Workspace-Id": os.environ["FLYQUERY_WORKSPACE_ID"],
        })
        api = AgentTablesApi(client)
        try:
            page: PaginatedSchemaChangeRead = await api.list_changes(
                table_id=os.environ["FLYQUERY_TABLE_ID"],
                x_agent_token=os.environ["FLYQUERY_AGENT_TOKEN"],
                _request_timeout=15.0,
            )
            print(page.total)
        except ApiException as exc:
            print(f"HTTP {exc.status}")
            raise


asyncio.run(main())
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **table_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**PaginatedSchemaChangeRead**](PaginatedSchemaChangeRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **list_objects**
> PaginatedSchemaObjectRead list_objects(table_id, x_agent_token, x_correlation_id=x_correlation_id)

### Example

* Api Key Authentication (AgentToken):

```python
import asyncio
import os

from flyquery_sdk import ApiClient, Configuration
from flyquery_sdk.api import AgentTablesApi
from flyquery_sdk.exceptions import ApiException
from flyquery_sdk.models import PaginatedSchemaObjectRead


async def main():
    async with ApiClient(Configuration(host=os.environ["FLYQUERY_URL"])) as client:
        client.default_headers.update({
            "X-Tenant-Id": os.environ["FLYQUERY_TENANT_ID"],
            "X-Workspace-Id": os.environ["FLYQUERY_WORKSPACE_ID"],
        })
        api = AgentTablesApi(client)
        try:
            page: PaginatedSchemaObjectRead = await api.list_objects(
                table_id=os.environ["FLYQUERY_TABLE_ID"],
                x_agent_token=os.environ["FLYQUERY_AGENT_TOKEN"],
                _request_timeout=15.0,
            )
            print(page.total)
        except ApiException as exc:
            print(f"HTTP {exc.status}")
            raise


asyncio.run(main())
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **table_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**PaginatedSchemaObjectRead**](PaginatedSchemaObjectRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **list_snapshots**
> PaginatedSnapshotRead list_snapshots(table_id, x_agent_token, x_correlation_id=x_correlation_id)

### Example

* Api Key Authentication (AgentToken):

```python
import asyncio
import os

from flyquery_sdk import ApiClient, Configuration
from flyquery_sdk.api import AgentTablesApi
from flyquery_sdk.exceptions import ApiException
from flyquery_sdk.models import PaginatedSnapshotRead


async def main():
    async with ApiClient(Configuration(host=os.environ["FLYQUERY_URL"])) as client:
        client.default_headers.update({
            "X-Tenant-Id": os.environ["FLYQUERY_TENANT_ID"],
            "X-Workspace-Id": os.environ["FLYQUERY_WORKSPACE_ID"],
        })
        api = AgentTablesApi(client)
        try:
            page: PaginatedSnapshotRead = await api.list_snapshots(
                table_id=os.environ["FLYQUERY_TABLE_ID"],
                x_agent_token=os.environ["FLYQUERY_AGENT_TOKEN"],
                _request_timeout=15.0,
            )
            print(page.total)
        except ApiException as exc:
            print(f"HTTP {exc.status}")
            raise


asyncio.run(main())
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **table_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**PaginatedSnapshotRead**](PaginatedSnapshotRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **list_tables**
> PaginatedTableRead list_tables(dataset_id, x_agent_token, x_correlation_id=x_correlation_id)

### Example

* Api Key Authentication (AgentToken):

```python
import asyncio
import os

from flyquery_sdk import ApiClient, Configuration
from flyquery_sdk.api import AgentTablesApi
from flyquery_sdk.exceptions import ApiException
from flyquery_sdk.models import PaginatedTableRead


async def main():
    async with ApiClient(Configuration(host=os.environ["FLYQUERY_URL"])) as client:
        client.default_headers.update({
            "X-Tenant-Id": os.environ["FLYQUERY_TENANT_ID"],
            "X-Workspace-Id": os.environ["FLYQUERY_WORKSPACE_ID"],
        })
        api = AgentTablesApi(client)
        try:
            page: PaginatedTableRead = await api.list_tables(
                dataset_id=os.environ["FLYQUERY_DATASET_ID"],
                x_agent_token=os.environ["FLYQUERY_AGENT_TOKEN"],
                _request_timeout=15.0,
            )
            print(page.total)
        except ApiException as exc:
            print(f"HTTP {exc.status}")
            raise


asyncio.run(main())
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **dataset_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**PaginatedTableRead**](PaginatedTableRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **search_tables**
> PaginatedTableRead search_tables(x_agent_token, q=q, name=name, dataset_id=dataset_id, kind=kind, is_active=is_active, limit=limit, offset=offset, x_correlation_id=x_correlation_id)

### Example

* Api Key Authentication (AgentToken):

```python
import asyncio
import os

from flyquery_sdk import ApiClient, Configuration
from flyquery_sdk.api import AgentTablesApi
from flyquery_sdk.exceptions import ApiException
from flyquery_sdk.models import PaginatedTableRead


async def main():
    async with ApiClient(Configuration(host=os.environ["FLYQUERY_URL"])) as client:
        client.default_headers.update({
            "X-Tenant-Id": os.environ["FLYQUERY_TENANT_ID"],
            "X-Workspace-Id": os.environ["FLYQUERY_WORKSPACE_ID"],
        })
        api = AgentTablesApi(client)
        try:
            page: PaginatedTableRead = await api.search_tables(
                dataset_id=os.environ["FLYQUERY_DATASET_ID"],
                x_agent_token=os.environ["FLYQUERY_AGENT_TOKEN"],
                _request_timeout=15.0,
            )
            print(page.total)
        except ApiException as exc:
            print(f"HTTP {exc.status}")
            raise


asyncio.run(main())
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **q** | **str**|  | [optional] 
 **name** | **str**|  | [optional] 
 **dataset_id** | **str**|  | [optional] 
 **kind** | **str**|  | [optional] 
 **is_active** | **bool**|  | [optional] [default to False]
 **limit** | **int**|  | [optional] [default to 100]
 **offset** | **int**|  | [optional] [default to 0]
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**PaginatedTableRead**](PaginatedTableRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

