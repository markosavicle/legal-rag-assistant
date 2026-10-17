import type {
	IDataObject,
	IExecuteFunctions,
	IHttpRequestMethods,
	IHttpRequestOptions,
	ILoadOptionsFunctions,
	INodePropertyOptions,
} from 'n8n-workflow';

type Context = IExecuteFunctions | ILoadOptionsFunctions;

export async function baseUrl(this: Context): Promise<string> {
	const credentials = await this.getCredentials('legalRagApi');
	return (credentials.baseUrl as string).replace(/\/+$/, '');
}

/** Calls the Legal RAG Assistant API with the credential's API key. */
export async function legalRagRequest(
	this: Context,
	method: IHttpRequestMethods,
	path: string,
	options: Partial<IHttpRequestOptions> = {},
) {
	return await this.helpers.httpRequestWithAuthentication.call(this, 'legalRagApi', {
		method,
		url: `${await baseUrl.call(this)}${path}`,
		json: true,
		// /search takes documents as a repeated query parameter: ?documents=1&documents=2
		arrayFormat: 'repeat',
		...options,
	});
}

export async function getDocuments(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
	const documents = (await legalRagRequest.call(this, 'GET', '/documents')) as IDataObject[];
	return documents.map((d) => ({
		name: d.filename as string,
		value: d.id as number,
		description: `ID ${d.id}, ${d.chunks} chunks`,
	}));
}
