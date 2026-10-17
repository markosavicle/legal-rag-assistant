import type {
	IDataObject,
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	JsonObject,
} from 'n8n-workflow';
import { NodeApiError, NodeConnectionTypes, NodeOperationError } from 'n8n-workflow';

import { duplicateDocumentId, formatCitations, simplifyAnswer, type AskResponse } from './answers';
import {
	documentFields,
	operationProperties,
	passageFields,
	questionFields,
	resourceProperty,
} from './descriptions';
import { getDocuments, legalRagRequest } from './GenericFunctions';

// Programmatic rather than declarative: Upload sends binary data as multipart form data and maps a
// 409 duplicate to the existing document, and Ask post-processes the answer (cited passages only,
// answered flag, formatted citations). Neither maps onto declarative routing cleanly.
export class LegalRag implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Legal RAG',
		name: 'legalRag',
		icon: { light: 'file:legalRag.svg', dark: 'file:legalRag.dark.svg' },
		group: ['transform'],
		version: [1],
		subtitle: '={{$parameter["operation"] + ": " + $parameter["resource"]}}',
		description: 'Answer questions about laws and contracts with cited passages, using Legal RAG Assistant',
		defaults: { name: 'Legal RAG' },
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		usableAsTool: true,
		credentials: [{ name: 'legalRagApi', required: true }],
		properties: [resourceProperty, ...operationProperties, ...questionFields, ...passageFields, ...documentFields],
	};

	methods = { loadOptions: { getDocuments } };

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];

		for (let i = 0; i < items.length; i++) {
			try {
				const resource = this.getNodeParameter('resource', i) as string;
				const operation = this.getNodeParameter('operation', i) as string;
				const results: IDataObject[] = [];

				if (resource === 'question' && operation === 'ask') {
					const question = (this.getNodeParameter('question', i) as string).trim();
					if (question.length < 3) {
						throw new NodeOperationError(this.getNode(), 'The question must be at least 3 characters', { itemIndex: i });
					}
					const documents = this.getNodeParameter('documents', i, []) as number[];
					const options = this.getNodeParameter('options', i, {}) as IDataObject;
					const response = (await legalRagRequest.call(this, 'POST', '/ask', {
						body: { question, documents: documents.map(Number), ...options },
					})) as AskResponse;
					const simple = simplifyAnswer(question, response);
					const shaped = { ...simple, citationsText: formatCitations(simple.citations) };
					results.push(this.getNodeParameter('simplify', i) ? shaped : { ...response, ...shaped });
				} else if (resource === 'passage' && operation === 'search') {
					const hits = (await legalRagRequest.call(this, 'GET', '/search', {
						qs: {
							q: this.getNodeParameter('query', i) as string,
							k: this.getNodeParameter('k', i) as number,
							mode: this.getNodeParameter('mode', i) as string,
							documents: (this.getNodeParameter('documents', i, []) as number[]).map(Number),
						},
					})) as IDataObject[];
					results.push(...hits);
				} else if (resource === 'document' && operation === 'getAll') {
					const documents = (await legalRagRequest.call(this, 'GET', '/documents')) as IDataObject[];
					const returnAll = this.getNodeParameter('returnAll', i) as boolean;
					results.push(...(returnAll ? documents : documents.slice(0, this.getNodeParameter('limit', i) as number)));
				} else if (resource === 'document' && operation === 'upload') {
					results.push(await upload.call(this, i));
				} else if (resource === 'document' && operation === 'delete') {
					const documentId = Number(this.getNodeParameter('documentId', i));
					await legalRagRequest.call(this, 'DELETE', `/documents/${documentId}`);
					results.push({ deleted: true, documentId });
				} else {
					throw new NodeOperationError(this.getNode(), `Unsupported operation "${operation}" for "${resource}"`, {
						itemIndex: i,
					});
				}

				returnData.push(...results.map((json) => ({ json, pairedItem: { item: i } })));
			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({ json: { error: (error as Error).message }, pairedItem: { item: i } });
					continue;
				}
				if (error instanceof NodeOperationError) {
					throw new NodeOperationError(this.getNode(), error, { itemIndex: i });
				}
				throw new NodeApiError(this.getNode(), error as JsonObject, { itemIndex: i });
			}
		}

		return [returnData];
	}
}

async function upload(this: IExecuteFunctions, i: number): Promise<IDataObject> {
	const binaryPropertyName = this.getNodeParameter('binaryPropertyName', i) as string;
	const options = this.getNodeParameter('options', i, {}) as { fileName?: string; skipDuplicates?: boolean };
	const binary = this.helpers.assertBinaryData(i, binaryPropertyName);
	const buffer = await this.helpers.getBinaryDataBuffer(i, binaryPropertyName);
	const fileName = options.fileName || binary.fileName;
	if (!fileName) {
		throw new NodeOperationError(this.getNode(), 'The file has no name; set "File Name" in the options', { itemIndex: i });
	}

	const form = new FormData();
	form.append('file', new Blob([new Uint8Array(buffer)], { type: binary.mimeType }), fileName);
	const response = (await legalRagRequest.call(this, 'POST', '/documents', {
		body: form,
		json: false,
		returnFullResponse: true,
		ignoreHttpStatusErrors: true,
	})) as { statusCode: number; body: unknown };

	const body = (typeof response.body === 'string' ? JSON.parse(response.body || '{}') : response.body) as IDataObject;
	if (response.statusCode === 201) {
		return { ...body, duplicate: false };
	}
	const detail = String(body.detail ?? '');
	const existing = duplicateDocumentId(detail);
	if (response.statusCode === 409 && options.skipDuplicates !== false && existing !== null) {
		return { document_id: existing, filename: fileName, duplicate: true, message: detail };
	}
	throw new NodeApiError(this.getNode(), body as JsonObject, {
		itemIndex: i,
		httpCode: String(response.statusCode),
		message: detail || `Upload failed with status ${response.statusCode}`,
	});
}
