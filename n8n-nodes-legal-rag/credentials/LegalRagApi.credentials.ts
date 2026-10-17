import type {
	IAuthenticateGeneric,
	Icon,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class LegalRagApi implements ICredentialType {
	name = 'legalRagApi';

	displayName = 'Legal RAG API';

	icon: Icon = { light: 'file:../nodes/LegalRag/legalRag.svg', dark: 'file:../nodes/LegalRag/legalRag.dark.svg' };

	documentationUrl = 'https://github.com/markosavicle/legal-rag-assistant/tree/main/n8n-nodes-legal-rag#credentials';

	properties: INodeProperties[] = [
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			default: 'http://host.docker.internal:8000',
			placeholder: 'https://legal-rag.example.com',
			description:
				'Where the Legal RAG Assistant API runs. From n8n in Docker on the same machine, use http://host.docker.internal:8000.',
			required: true,
		},
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			description: 'The API_KEY set on the server. Leave empty if the server runs without one.',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				'X-API-Key': '={{$credentials.apiKey}}',
			},
		},
	};

	// /documents requires the key when one is set, so this checks both the URL and the key.
	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.baseUrl.replace(/\\/+$/, "")}}',
			url: '/documents',
			method: 'GET',
		},
	};
}
