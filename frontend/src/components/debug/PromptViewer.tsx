interface PromptViewerProps {
  preview: string;
  fullPrompt?: string | null;
  fullPromptRequested: boolean;
}

export function PromptViewer({ preview, fullPrompt, fullPromptRequested }: PromptViewerProps) {
  const showFullPromptHint = fullPromptRequested && !fullPrompt;
  return (
    <div className="space-y-2">
      <div>
        <h4 className="text-xs font-semibold text-gray-700 mb-1">Prompt preview</h4>
        <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-2 max-h-60 overflow-auto whitespace-pre-wrap break-words">
{preview || '(empty)'}
        </pre>
      </div>
      {fullPrompt && (
        <details>
          <summary className="cursor-pointer text-xs font-semibold text-gray-700">
            Full prompt (dev mode)
          </summary>
          <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-2 mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words">
{fullPrompt}
          </pre>
        </details>
      )}
      {showFullPromptHint && (
        <p className="text-xs text-amber-600">
          Full prompt was requested but server did not return it — check `LITERATURE_DEV_MODE`.
        </p>
      )}
    </div>
  );
}
