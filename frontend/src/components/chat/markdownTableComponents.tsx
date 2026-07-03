import type { Components } from 'react-markdown';

/**
 * Shared markdown table renderer for assistant answers.
 *
 * Markdown tables often exceed the desktop message column. The wrapper keeps
 * the answer readable without letting the table widen the whole app shell.
 */
export const markdownTableComponents = {
  table({ children }) {
    return (
      <div
        role="region"
        aria-label="可横向滚动的表格"
        className="my-3 w-full min-w-0 max-w-full overflow-x-auto rounded-md border border-outline-variant/60 bg-surface-lowest [scrollbar-width:thin]"
      >
        <table className="m-0 w-max min-w-full border-collapse text-xs leading-5">
          {children}
        </table>
      </div>
    );
  },
  thead({ children }) {
    return <thead className="bg-surface-high text-foreground">{children}</thead>;
  },
  th({ children }) {
    return (
      <th className="border-b border-r border-outline-variant/50 px-3 py-2 text-left align-bottom font-semibold last:border-r-0">
        {children}
      </th>
    );
  },
  td({ children }) {
    return (
      <td className="border-b border-r border-outline-variant/35 px-3 py-2 align-top last:border-r-0">
        {children}
      </td>
    );
  },
} satisfies Components;
