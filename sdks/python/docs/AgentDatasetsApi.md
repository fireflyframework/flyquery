# flyquery_sdk.AgentDatasetsApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**list_datasets**](AgentDatasetsApi.md#list_datasets) | **GET** /api/v1/agent/datasets | Search / filter datasets visible to this agent&#39;s tenant.
[**read**](AgentDatasetsApi.md#read) | **GET** /api/v1/agent/datasets/{dataset_id} | Fetch a single dataset by id.
[**read_by_name**](AgentDatasetsApi.md#read_by_name) | **GET** /api/v1/agent/datasets/by-name/{name} | Resolve a dataset by &#x60;&#x60;(tenant, workspace, name)&#x60;&#x60;.


# **list_datasets**
> PaginatedDatasetRead list_datasets(x_agent_token, q=q, name=name, status=status, workspace_id=workspace_id, limit=limit, offset=offset, x_correlation_id=x_correlation_id)

Search / filter datasets visible to this agent's tenant.

### Example

* Api Key Authentication (AgentToken):

```python
import asyncio
import os

from flyquery_sdk import ApiClient, Configuration
from flyquery_sdk.api import AgentDatasetsApi
from flyquery_sdk.exceptions import ApiException
from flyquery_sdk.models import PaginatedDatasetRead


async def main():
    async with ApiClient(Configuration(host=os.environ["FLYQUERY_URL"])) as client:
        client.default_headers.update({
            "X-Tenant-Id": os.environ["FLYQUERY_TENANT_ID"],
            "X-Workspace-Id": os.environ["FLYQUERY_WORKSPACE_ID"],
        })
        api = AgentDatasetsApi(client)
        try:
            page: PaginatedDatasetRead = await api.list_datasets(
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
 **q** | **str**|  | [optional] [default to &#39;null&#39;]
 **name** | **str**|  | [optional] 
 **status** | **str**|  | [optional] 
 **workspace_id** | **str**|  | [optional] 
 **limit** | **int**|  | [optional] [default to 100]
 **offset** | **int**|  | [optional] [default to 0]
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**PaginatedDatasetRead**](PaginatedDatasetRead.md)

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

# **read**
> DatasetRead read(dataset_id, x_agent_token, x_correlation_id=x_correlation_id)

Fetch a single dataset by id.

### Example

* Api Key Authentication (AgentToken):

```python
import flyquery_sdk
from flyquery_sdk.models.dataset_read import DatasetRead
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
    api_instance = flyquery_sdk.AgentDatasetsApi(api_client)
    dataset_id = 'dataset_id_example' # str | 
    x_agent_token = 'fqt_live_aBcDeF1234567890aBcDeF1234567890' # str | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
    x_correlation_id = UUID('550e8400-e29b-41d4-a716-446655440000') # UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. (optional)

    try:
        # Fetch a single dataset by id.
        api_response = await api_instance.read(dataset_id, x_agent_token, x_correlation_id=x_correlation_id)
        print("The response of AgentDatasetsApi->read:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentDatasetsApi->read: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **dataset_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**DatasetRead**](DatasetRead.md)

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

# **read_by_name**
> DatasetRead read_by_name(name, x_agent_token, x_correlation_id=x_correlation_id)

Resolve a dataset by ``(tenant, workspace, name)``.

### Example

* Api Key Authentication (AgentToken):

```python
import flyquery_sdk
from flyquery_sdk.models.dataset_read import DatasetRead
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
    api_instance = flyquery_sdk.AgentDatasetsApi(api_client)
    name = 'name_example' # str | 
    x_agent_token = 'fqt_live_aBcDeF1234567890aBcDeF1234567890' # str | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
    x_correlation_id = UUID('550e8400-e29b-41d4-a716-446655440000') # UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. (optional)

    try:
        # Resolve a dataset by ``(tenant, workspace, name)``.
        api_response = await api_instance.read_by_name(name, x_agent_token, x_correlation_id=x_correlation_id)
        print("The response of AgentDatasetsApi->read_by_name:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentDatasetsApi->read_by_name: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **name** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**DatasetRead**](DatasetRead.md)

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

