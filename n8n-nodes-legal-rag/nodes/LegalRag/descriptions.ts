import type { INodeProperties } from 'n8n-workflow';

const documentsFilter = (resource: string, operation: string): INodeProperties => ({
	displayName: 'Document Names or IDs',
	name: 'documents',
	type: 'multiOptions',
	typeOptions: { loadOptionsMethod: 'getDocuments' },
	default: [],
	description:
		'Only use these documents, e.g. one of two contracts. Leave empty to use all indexed documents. Choose from the list, or specify IDs using an <a href="https://docs.n8n.io/code/expressions/">expression</a>.',
	displayOptions: { show: { resource: [resource], operation: [operation] } },
});

const searchMode = {
	displayName: 'Search Mode',
	name: 'mode',
	type: 'options',
	options: [
		{ name: 'Semantic', value: 'vector', description: 'Similar meaning (best on the evaluation set)' },
		{ name: 'Hybrid', value: 'hybrid', description: 'Semantic and keyword results fused' },
		{ name: 'Keyword', value: 'keyword', description: 'Exact words and named articles ("član 62")' },
	],
	default: 'vector',
} satisfies INodeProperties;

export const resourceProperty: INodeProperties = {
	displayName: 'Resource',
	name: 'resource',
	type: 'options',
	noDataExpression: true,
	options: [
		{ name: 'Question', value: 'question' },
		{ name: 'Passage', value: 'passage' },
		{ name: 'Document', value: 'document' },
	],
	default: 'question',
};

export const operationProperties: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['question'] } },
		options: [
			{
				name: 'Ask',
				value: 'ask',
				description: 'Answer a question from the documents, with citations',
				action: 'Ask a question',
			},
		],
		default: 'ask',
	},
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['passage'] } },
		options: [
			{
				name: 'Search',
				value: 'search',
				description: 'Find the passages most relevant to a query, without generating an answer',
				action: 'Search passages',
			},
		],
		default: 'search',
	},
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['document'] } },
		options: [
			{ name: 'Delete', value: 'delete', description: 'Remove a document and its passages', action: 'Delete a document' },
			{ name: 'Get Many', value: 'getAll', description: 'List indexed documents', action: 'Get many documents' },
			{
				name: 'Upload',
				value: 'upload',
				description: 'Index a PDF, DOCX, TXT or MD file from binary data',
				action: 'Upload a document',
			},
		],
		default: 'upload',
	},
];

export const questionFields: INodeProperties[] = [
	{
		displayName: 'Question',
		name: 'question',
		type: 'string',
		typeOptions: { rows: 2 },
		required: true,
		default: '',
		placeholder: 'e.g. Koliko najmanje traje godišnji odmor?',
		description: 'In Serbian (Latin or Cyrillic) or English. The answer uses the same language and script.',
		displayOptions: { show: { resource: ['question'], operation: ['ask'] } },
	},
	documentsFilter('question', 'ask'),
	{
		displayName: 'Simplify',
		name: 'simplify',
		type: 'boolean',
		default: true,
		description:
			'Whether to return only the answer, whether it was found, and the passages it cites, instead of the raw response with every retrieved passage, token usage and timings',
		displayOptions: { show: { resource: ['question'], operation: ['ask'] } },
	},
	{
		displayName: 'Options',
		name: 'options',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		displayOptions: { show: { resource: ['question'], operation: ['ask'] } },
		options: [
			searchMode,
			{
				displayName: 'Passages to Retrieve',
				name: 'k',
				type: 'number',
				typeOptions: { minValue: 1, maxValue: 20 },
				default: 5,
				description: 'How many passages the answer may draw on',
			},
		],
	},
];

export const passageFields: INodeProperties[] = [
	{
		displayName: 'Query',
		name: 'query',
		type: 'string',
		required: true,
		default: '',
		placeholder: 'e.g. probni rad',
		displayOptions: { show: { resource: ['passage'], operation: ['search'] } },
	},
	documentsFilter('passage', 'search'),
	{
		displayName: 'Passages to Return',
		name: 'k',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 50 },
		default: 5,
		description: 'How many of the best-matching passages to return',
		displayOptions: { show: { resource: ['passage'], operation: ['search'] } },
	},
	{
		...searchMode,
		displayOptions: { show: { resource: ['passage'], operation: ['search'] } },
	},
];

export const documentFields: INodeProperties[] = [
	{
		displayName: 'Input Binary Field',
		name: 'binaryPropertyName',
		type: 'string',
		required: true,
		default: 'data',
		hint: 'The name of the input binary field containing the file to index',
		displayOptions: { show: { resource: ['document'], operation: ['upload'] } },
	},
	{
		displayName: 'Options',
		name: 'options',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		displayOptions: { show: { resource: ['document'], operation: ['upload'] } },
		options: [
			{
				displayName: 'File Name',
				name: 'fileName',
				type: 'string',
				default: '',
				description: 'Name to index the file under. Defaults to the binary file name.',
			},
			{
				displayName: 'Skip If Already Indexed',
				name: 'skipDuplicates',
				type: 'boolean',
				default: true,
				description:
					'Whether to return the existing document instead of failing when the same file was indexed before, so a workflow can safely run twice on the same file',
			},
		],
	},
	{
		displayName: 'Document Name or ID',
		name: 'documentId',
		type: 'options',
		typeOptions: { loadOptionsMethod: 'getDocuments' },
		required: true,
		default: '',
		description:
			'Choose from the list, or specify an ID using an <a href="https://docs.n8n.io/code/expressions/">expression</a>',
		displayOptions: { show: { resource: ['document'], operation: ['delete'] } },
	},
	{
		displayName: 'Return All',
		name: 'returnAll',
		type: 'boolean',
		default: false,
		description: 'Whether to return all results or only up to a given limit',
		displayOptions: { show: { resource: ['document'], operation: ['getAll'] } },
	},
	{
		displayName: 'Limit',
		name: 'limit',
		type: 'number',
		typeOptions: { minValue: 1 },
		default: 50,
		description: 'Max number of results to return',
		displayOptions: { show: { resource: ['document'], operation: ['getAll'], returnAll: [false] } },
	},
];
