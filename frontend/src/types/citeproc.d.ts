// Minimal ambient declaration for the `citeproc` (citeproc-js) package, which
// ships as plain JS without bundled types. Only the surface we use is typed.
declare module 'citeproc' {
  export interface CiteprocSys {
    retrieveLocale: (lang: string) => string | false;
    retrieveItem: (id: string) => unknown;
  }

  export interface CiteprocBibliographyParams {
    bibstart?: string;
    bibend?: string;
    entry_ids?: string[] | string[][];
    bibliography_errors?: string[];
    maxoffset?: number;
    hangingindent?: boolean | number;
    'second-field-align'?: boolean | string;
  }

  export interface CiteprocCitation {
    citationItems: Array<{ id: string; locator?: string; label?: string; prefix?: string; suffix?: string }>;
    properties?: { noteIndex?: number };
  }

  export class Engine {
    constructor(sys: CiteprocSys, style: string, lang?: string, forceLang?: boolean);
    updateItems(ids: string[]): void;
    updateUncitedItems(ids: string[]): void;
    previewCitationCluster(
      citation: CiteprocCitation,
      citationsPre: Array<[string, number]>,
      citationsPost: Array<[string, number]>,
      format: 'html' | 'text' | 'rtf',
    ): string;
    makeBibliography(filter?: unknown): [CiteprocBibliographyParams, string[]];
  }

  const CSL: { Engine: typeof Engine };
  export default CSL;
}
