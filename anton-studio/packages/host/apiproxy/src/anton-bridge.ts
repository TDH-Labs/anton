import { LlmAdapter, LlmProviderInfo, GenerateOptions, StreamChunk } from '@deepseek-ai/dsh-llm'

export class AntonFastApiAdapter extends LlmAdapter {
    override providerInfo(provider: string): LlmProviderInfo {
        return { id: provider, name: 'Anton FastAPI' }
    }

    override async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
        const userMsg = options.messages.filter(m => m.role === 'user').pop();
        const content = userMsg?.content || [];
        let promptText = '';
        if (typeof content === 'string') promptText = content;
        else if (Array.isArray(content)) {
            promptText = content.map(p => p.type === 'text' ? p.text : '').join('\n');
        }

        const res = await globalThis.fetch("http://localhost:8799/api/chat", {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptText })
        });
        
        if (!res.ok) throw new Error(`Anton FastAPI failed: ${res.status}`);
        const data = await res.json();
        
        const fullText = data.note_path 
            ? `${data.reply}\n\n[Inspect ${data.note_path}](file://${data.note_path})` 
            : data.reply;

        yield { type: 'block-start', blockType: 'text', index: 0 };
        yield { type: 'text-delta', text: fullText, index: 0 };
        yield { type: 'block-end', index: 0, block: { type: 'text', text: fullText } };
        yield { type: 'finish', reason: { kind: 'stop' } };
    }
}
