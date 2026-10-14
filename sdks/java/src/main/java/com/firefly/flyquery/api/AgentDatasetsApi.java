package com.firefly.flyquery.api;

import com.firefly.flyquery.ApiClient;

import com.firefly.flyquery.model.DatasetRead;
import com.firefly.flyquery.model.PaginatedDatasetRead;
import java.util.UUID;

import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Arrays;
import java.util.stream.Collectors;

import org.springframework.core.io.FileSystemResource;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.reactive.function.client.WebClient.ResponseSpec;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;

@jakarta.annotation.Generated(value = "org.openapitools.codegen.languages.JavaClientCodegen", date = "2026-10-14T13:20:41.405226-07:00[America/Los_Angeles]", comments = "Generator version: 7.22.0")
public class AgentDatasetsApi {
    private ApiClient apiClient;

    public AgentDatasetsApi() {
        this(new ApiClient());
    }

    public AgentDatasetsApi(ApiClient apiClient) {
        this.apiClient = apiClient;
    }

    public ApiClient getApiClient() {
        return apiClient;
    }

    public void setApiClient(ApiClient apiClient) {
        this.apiClient = apiClient;
    }

    /**
     * Search / filter datasets visible to this agent&#39;s tenant.
     * 
     * <p><b>200</b> - Successful response
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param q The q parameter
     * @param name The name parameter
     * @param status The status parameter
     * @param workspaceId The workspaceId parameter
     * @param limit The limit parameter
     * @param offset The offset parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return PaginatedDatasetRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    private ResponseSpec listDatasetsRequestCreation(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable String q, @jakarta.annotation.Nullable String name, @jakarta.annotation.Nullable String status, @jakarta.annotation.Nullable String workspaceId, @jakarta.annotation.Nullable Integer limit, @jakarta.annotation.Nullable Integer offset, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        Object postBody = null;
        // verify the required parameter 'xAgentToken' is set
        if (xAgentToken == null) {
            throw new WebClientResponseException("Missing the required parameter 'xAgentToken' when calling listDatasets", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // create path and map variables
        final Map<String, Object> pathParams = new HashMap<String, Object>();

        final MultiValueMap<String, String> queryParams = new LinkedMultiValueMap<String, String>();
        final HttpHeaders headerParams = new HttpHeaders();
        final MultiValueMap<String, String> cookieParams = new LinkedMultiValueMap<String, String>();
        final MultiValueMap<String, Object> formParams = new LinkedMultiValueMap<String, Object>();

        queryParams.putAll(apiClient.parameterToMultiValueMap(null, "q", q));
        queryParams.putAll(apiClient.parameterToMultiValueMap(null, "name", name));
        queryParams.putAll(apiClient.parameterToMultiValueMap(null, "status", status));
        queryParams.putAll(apiClient.parameterToMultiValueMap(null, "workspace_id", workspaceId));
        queryParams.putAll(apiClient.parameterToMultiValueMap(null, "limit", limit));
        queryParams.putAll(apiClient.parameterToMultiValueMap(null, "offset", offset));

        if (xAgentToken != null)
        headerParams.add("X-Agent-Token", apiClient.parameterToString(xAgentToken));
        if (xCorrelationId != null)
        headerParams.add("X-Correlation-Id", apiClient.parameterToString(xCorrelationId));
        final String[] localVarAccepts = {
            "application/json"
        };
        final List<MediaType> localVarAccept = apiClient.selectHeaderAccept(localVarAccepts);
        final String[] localVarContentTypes = { };
        final MediaType localVarContentType = apiClient.selectHeaderContentType(localVarContentTypes);

        String[] localVarAuthNames = new String[] { "AgentToken" };

        ParameterizedTypeReference<PaginatedDatasetRead> localVarReturnType = new ParameterizedTypeReference<PaginatedDatasetRead>() {};
        return apiClient.invokeAPI("/api/v1/agent/datasets", HttpMethod.GET, pathParams, queryParams, postBody, headerParams, cookieParams, formParams, localVarAccept, localVarContentType, localVarAuthNames, localVarReturnType);
    }

    /**
     * Search / filter datasets visible to this agent&#39;s tenant.
     * 
     * <p><b>200</b> - Successful response
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param q The q parameter
     * @param name The name parameter
     * @param status The status parameter
     * @param workspaceId The workspaceId parameter
     * @param limit The limit parameter
     * @param offset The offset parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return PaginatedDatasetRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<PaginatedDatasetRead> listDatasets(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable String q, @jakarta.annotation.Nullable String name, @jakarta.annotation.Nullable String status, @jakarta.annotation.Nullable String workspaceId, @jakarta.annotation.Nullable Integer limit, @jakarta.annotation.Nullable Integer offset, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<PaginatedDatasetRead> localVarReturnType = new ParameterizedTypeReference<PaginatedDatasetRead>() {};
        return listDatasetsRequestCreation(xAgentToken, q, name, status, workspaceId, limit, offset, xCorrelationId).bodyToMono(localVarReturnType);
    }

    /**
     * Search / filter datasets visible to this agent&#39;s tenant.
     * 
     * <p><b>200</b> - Successful response
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param q The q parameter
     * @param name The name parameter
     * @param status The status parameter
     * @param workspaceId The workspaceId parameter
     * @param limit The limit parameter
     * @param offset The offset parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseEntity&lt;PaginatedDatasetRead&gt;
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ResponseEntity<PaginatedDatasetRead>> listDatasetsWithHttpInfo(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable String q, @jakarta.annotation.Nullable String name, @jakarta.annotation.Nullable String status, @jakarta.annotation.Nullable String workspaceId, @jakarta.annotation.Nullable Integer limit, @jakarta.annotation.Nullable Integer offset, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<PaginatedDatasetRead> localVarReturnType = new ParameterizedTypeReference<PaginatedDatasetRead>() {};
        return listDatasetsRequestCreation(xAgentToken, q, name, status, workspaceId, limit, offset, xCorrelationId).toEntity(localVarReturnType);
    }

    /**
     * Search / filter datasets visible to this agent&#39;s tenant.
     * 
     * <p><b>200</b> - Successful response
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param q The q parameter
     * @param name The name parameter
     * @param status The status parameter
     * @param workspaceId The workspaceId parameter
     * @param limit The limit parameter
     * @param offset The offset parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseSpec
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public ResponseSpec listDatasetsWithResponseSpec(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable String q, @jakarta.annotation.Nullable String name, @jakarta.annotation.Nullable String status, @jakarta.annotation.Nullable String workspaceId, @jakarta.annotation.Nullable Integer limit, @jakarta.annotation.Nullable Integer offset, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        return listDatasetsRequestCreation(xAgentToken, q, name, status, workspaceId, limit, offset, xCorrelationId);
    }

    /**
     * Fetch a single dataset by id.
     * 
     * <p><b>200</b> - Successful response
     * @param datasetId The datasetId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return DatasetRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    private ResponseSpec readRequestCreation(@jakarta.annotation.Nullable String datasetId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        Object postBody = null;
        // verify the required parameter 'datasetId' is set
        if (datasetId == null) {
            throw new WebClientResponseException("Missing the required parameter 'datasetId' when calling read", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // verify the required parameter 'xAgentToken' is set
        if (xAgentToken == null) {
            throw new WebClientResponseException("Missing the required parameter 'xAgentToken' when calling read", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // create path and map variables
        final Map<String, Object> pathParams = new HashMap<String, Object>();

        pathParams.put("dataset_id", datasetId);

        final MultiValueMap<String, String> queryParams = new LinkedMultiValueMap<String, String>();
        final HttpHeaders headerParams = new HttpHeaders();
        final MultiValueMap<String, String> cookieParams = new LinkedMultiValueMap<String, String>();
        final MultiValueMap<String, Object> formParams = new LinkedMultiValueMap<String, Object>();

        if (xAgentToken != null)
        headerParams.add("X-Agent-Token", apiClient.parameterToString(xAgentToken));
        if (xCorrelationId != null)
        headerParams.add("X-Correlation-Id", apiClient.parameterToString(xCorrelationId));
        final String[] localVarAccepts = { 
            "application/json"
        };
        final List<MediaType> localVarAccept = apiClient.selectHeaderAccept(localVarAccepts);
        final String[] localVarContentTypes = { };
        final MediaType localVarContentType = apiClient.selectHeaderContentType(localVarContentTypes);

        String[] localVarAuthNames = new String[] { "AgentToken" };

        ParameterizedTypeReference<DatasetRead> localVarReturnType = new ParameterizedTypeReference<DatasetRead>() {};
        return apiClient.invokeAPI("/api/v1/agent/datasets/{dataset_id}", HttpMethod.GET, pathParams, queryParams, postBody, headerParams, cookieParams, formParams, localVarAccept, localVarContentType, localVarAuthNames, localVarReturnType);
    }

    /**
     * Fetch a single dataset by id.
     * 
     * <p><b>200</b> - Successful response
     * @param datasetId The datasetId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return DatasetRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<DatasetRead> read(@jakarta.annotation.Nullable String datasetId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<DatasetRead> localVarReturnType = new ParameterizedTypeReference<DatasetRead>() {};
        return readRequestCreation(datasetId, xAgentToken, xCorrelationId).bodyToMono(localVarReturnType);
    }

    /**
     * Fetch a single dataset by id.
     * 
     * <p><b>200</b> - Successful response
     * @param datasetId The datasetId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseEntity&lt;DatasetRead&gt;
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ResponseEntity<DatasetRead>> readWithHttpInfo(@jakarta.annotation.Nullable String datasetId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<DatasetRead> localVarReturnType = new ParameterizedTypeReference<DatasetRead>() {};
        return readRequestCreation(datasetId, xAgentToken, xCorrelationId).toEntity(localVarReturnType);
    }

    /**
     * Fetch a single dataset by id.
     * 
     * <p><b>200</b> - Successful response
     * @param datasetId The datasetId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseSpec
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public ResponseSpec readWithResponseSpec(@jakarta.annotation.Nullable String datasetId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        return readRequestCreation(datasetId, xAgentToken, xCorrelationId);
    }

    /**
     * Resolve a dataset by &#x60;&#x60;(tenant, workspace, name)&#x60;&#x60;.
     * 
     * <p><b>200</b> - Successful response
     * @param name The name parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return DatasetRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    private ResponseSpec readByNameRequestCreation(@jakarta.annotation.Nullable String name, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        Object postBody = null;
        // verify the required parameter 'name' is set
        if (name == null) {
            throw new WebClientResponseException("Missing the required parameter 'name' when calling readByName", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // verify the required parameter 'xAgentToken' is set
        if (xAgentToken == null) {
            throw new WebClientResponseException("Missing the required parameter 'xAgentToken' when calling readByName", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // create path and map variables
        final Map<String, Object> pathParams = new HashMap<String, Object>();

        pathParams.put("name", name);

        final MultiValueMap<String, String> queryParams = new LinkedMultiValueMap<String, String>();
        final HttpHeaders headerParams = new HttpHeaders();
        final MultiValueMap<String, String> cookieParams = new LinkedMultiValueMap<String, String>();
        final MultiValueMap<String, Object> formParams = new LinkedMultiValueMap<String, Object>();

        if (xAgentToken != null)
        headerParams.add("X-Agent-Token", apiClient.parameterToString(xAgentToken));
        if (xCorrelationId != null)
        headerParams.add("X-Correlation-Id", apiClient.parameterToString(xCorrelationId));
        final String[] localVarAccepts = { 
            "application/json"
        };
        final List<MediaType> localVarAccept = apiClient.selectHeaderAccept(localVarAccepts);
        final String[] localVarContentTypes = { };
        final MediaType localVarContentType = apiClient.selectHeaderContentType(localVarContentTypes);

        String[] localVarAuthNames = new String[] { "AgentToken" };

        ParameterizedTypeReference<DatasetRead> localVarReturnType = new ParameterizedTypeReference<DatasetRead>() {};
        return apiClient.invokeAPI("/api/v1/agent/datasets/by-name/{name}", HttpMethod.GET, pathParams, queryParams, postBody, headerParams, cookieParams, formParams, localVarAccept, localVarContentType, localVarAuthNames, localVarReturnType);
    }

    /**
     * Resolve a dataset by &#x60;&#x60;(tenant, workspace, name)&#x60;&#x60;.
     * 
     * <p><b>200</b> - Successful response
     * @param name The name parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return DatasetRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<DatasetRead> readByName(@jakarta.annotation.Nullable String name, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<DatasetRead> localVarReturnType = new ParameterizedTypeReference<DatasetRead>() {};
        return readByNameRequestCreation(name, xAgentToken, xCorrelationId).bodyToMono(localVarReturnType);
    }

    /**
     * Resolve a dataset by &#x60;&#x60;(tenant, workspace, name)&#x60;&#x60;.
     * 
     * <p><b>200</b> - Successful response
     * @param name The name parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseEntity&lt;DatasetRead&gt;
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ResponseEntity<DatasetRead>> readByNameWithHttpInfo(@jakarta.annotation.Nullable String name, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<DatasetRead> localVarReturnType = new ParameterizedTypeReference<DatasetRead>() {};
        return readByNameRequestCreation(name, xAgentToken, xCorrelationId).toEntity(localVarReturnType);
    }

    /**
     * Resolve a dataset by &#x60;&#x60;(tenant, workspace, name)&#x60;&#x60;.
     * 
     * <p><b>200</b> - Successful response
     * @param name The name parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseSpec
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public ResponseSpec readByNameWithResponseSpec(@jakarta.annotation.Nullable String name, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        return readByNameRequestCreation(name, xAgentToken, xCorrelationId);
    }
}
