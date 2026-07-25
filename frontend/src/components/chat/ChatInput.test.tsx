import { createRef, useRef, useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  ChatInput,
  chatAttachmentFingerprint,
  type ChatAttachment,
  type ChatInputHandle,
} from './ChatInput';

describe('ChatInput', () => {
  it('renders a textarea with the provided placeholder', () => {
    render(<ChatInput onSubmit={() => {}} placeholder="ask about this paper" />);
    expect(screen.getByPlaceholderText('ask about this paper')).toBeInTheDocument();
  });

  it('exposes a stable accessible textbox name', () => {
    render(<ChatInput onSubmit={() => {}} placeholder="ask about this paper" />);
    expect(screen.getByRole('textbox', { name: '对话输入' })).toBeInTheDocument();
  });

  it('allows callers to customize the accessible textbox name', () => {
    render(<ChatInput onSubmit={() => {}} ariaLabel="侧边栏问题输入" />);
    expect(screen.getByRole('textbox', { name: '侧边栏问题输入' })).toBeInTheDocument();
  });

  it('links the accessible name through a native label for desktop automation', () => {
    render(<ChatInput onSubmit={() => {}} ariaLabel="侧边栏问题输入" />);
    const textarea = screen.getByRole('textbox', { name: '侧边栏问题输入' }) as HTMLTextAreaElement;
    const label = screen.getByText('侧边栏问题输入');
    expect(label).toHaveAttribute('for', textarea.id);
    expect(textarea).toHaveAttribute('name', 'scholar-ai-question');
    expect(textarea).toHaveAttribute('data-scholar-ai-role', 'smartread-composer-input');
  });

  it('can focus the composer on mount', () => {
    render(<ChatInput onSubmit={() => {}} autoFocus />);
    expect(screen.getByRole('textbox', { name: '对话输入' })).toHaveFocus();
  });

  it('exposes focus, select-all, and clear controls through the composer handle', () => {
    const ref = createRef<ChatInputHandle>();
    render(<ChatInput ref={ref} onSubmit={() => {}} />);
    const ta = screen.getByRole('textbox', { name: '对话输入' }) as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'select this draft' } });

    act(() => {
      ref.current?.selectAll();
    });
    expect(ta).toHaveFocus();
    expect(ta.selectionStart).toBe(0);
    expect(ta.selectionEnd).toBe('select this draft'.length);

    act(() => {
      ref.current?.clear();
    });
    expect(ta).toHaveValue('');
  });

  it('provides a stable clear button for draft text', () => {
    render(<ChatInput onSubmit={() => {}} />);
    const ta = screen.getByRole('textbox', { name: '对话输入' }) as HTMLTextAreaElement;
    expect(screen.queryByRole('button', { name: '清空输入' })).not.toBeInTheDocument();

    fireEvent.change(ta, { target: { value: 'temporary draft' } });
    fireEvent.click(screen.getByRole('button', { name: '清空输入' }));

    expect(ta).toHaveValue('');
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  });

  it('clears draft text during pointer press before click focus drift', () => {
    render(<ChatInput onSubmit={() => {}} />);
    const ta = screen.getByRole('textbox', { name: '对话输入' }) as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'temporary pointer draft' } });

    const clearButton = screen.getByRole('button', { name: '清空输入' });
    expect(fireEvent.pointerDown(clearButton)).toBe(false);

    expect(ta).toHaveValue('');
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  });

  it('clears draft text during pointer release when the host skips press handlers', () => {
    render(<ChatInput onSubmit={() => {}} />);
    const ta = screen.getByRole('textbox', { name: '对话输入' }) as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'temporary release draft' } });

    const clearButton = screen.getByRole('button', { name: '清空输入' });
    expect(fireEvent.pointerUp(clearButton)).toBe(false);

    expect(ta).toHaveValue('');
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  });

  it('allows the composer to be resized vertically', () => {
    render(<ChatInput onSubmit={() => {}} placeholder="ask about this paper" />);
    const textarea = screen.getByPlaceholderText('ask about this paper');
    expect(textarea).toHaveClass('resize-y');
    expect(textarea).toHaveClass('max-h-48');
  });

  it('submits with Ctrl+Enter by default and clears the text', () => {
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} />);
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'hello world' } });
    fireEvent.keyDown(ta, { key: 'Enter' });
    // Enter without modifier should NOT submit when submitKey=cmd-enter
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      text: 'hello world',
      attachments: [],
      attachmentsEnabled: false,
      projectReasoningBiasEnabled: undefined,
    });
    expect(ta.value).toBe('');
  });

  it('submits with bare Enter when submitKey=enter (Dialog parity)', () => {
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} submitKey="enter" />);
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'send me' } });
    fireEvent.keyDown(ta, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.change(ta, { target: { value: 'newline' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    // Shift+Enter inserts a newline → should not submit
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('does not submit while IME composition is active', () => {
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} />);
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '中文输入中' } });
    fireEvent.compositionStart(ta);
    fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.compositionEnd(ta);
    fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('disables both send and textarea when disabled', () => {
    render(<ChatInput onSubmit={() => {}} disabled />);
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement;
    const send = screen.getByRole('button', { name: '发送' });
    expect(ta).toBeDisabled();
    expect(send).toBeDisabled();
  });

  it('disables send when there is no text and no attachment', () => {
    render(<ChatInput onSubmit={() => {}} />);
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  });

  it('does NOT render the paperclip button when enableAttachments is false (default)', () => {
    render(<ChatInput onSubmit={() => {}} />);
    expect(
      screen.queryByLabelText(/添加图片附件/),
    ).not.toBeInTheDocument();
  });

  it('renders the paperclip button when enableAttachments is true', () => {
    render(<ChatInput onSubmit={() => {}} enableAttachments />);
    expect(
      screen.getByLabelText(/添加图片附件/),
    ).toBeInTheDocument();
  });

  it('shows manually uploaded images as ordinary attachments', async () => {
    render(<ChatInput onSubmit={() => {}} enableAttachments />);
    const fileInput = screen.getByLabelText('选择图片附件') as HTMLInputElement;
    const file = new File(['hello'], 'figure.png', { type: 'image/png' });

    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(await screen.findByText('图片附件 1/6')).toBeInTheDocument();
    expect(screen.getByAltText('figure.png')).toBeInTheDocument();
  });

  it('blocks button and Enter submission until a manual image finishes reading', async () => {
    const onSubmit = vi.fn();
    const pendingReader: { current: FileReader | null } = { current: null };
    const readSpy = vi.spyOn(FileReader.prototype, 'readAsDataURL').mockImplementation(function (
      this: FileReader,
      _blob: Blob,
    ): void {
      pendingReader.current = this;
    });

    try {
      render(<ChatInput onSubmit={onSubmit} enableAttachments submitKey="enter" />);
      const textarea = screen.getByRole('textbox', { name: '对话输入' });
      const fileInput = screen.getByLabelText('选择图片附件') as HTMLInputElement;
      const file = new File(['hello'], 'pending.png', { type: 'image/png' });

      fireEvent.change(textarea, { target: { value: '分析这张图片' } });
      act(() => {
        fireEvent.change(fileInput, { target: { files: [file] } });
        fireEvent.keyDown(textarea, { key: 'Enter' });
      });

      expect(onSubmit).not.toHaveBeenCalled();
      expect(screen.getByRole('status', { name: '正在读取图片' })).toBeInTheDocument();
      const sendButton = screen.getByRole('button', { name: '发送' });
      expect(sendButton).toBeDisabled();
      fireEvent.click(sendButton);
      expect(onSubmit).not.toHaveBeenCalled();

      const reader = pendingReader.current;
      if (!reader) throw new Error('Expected a pending FileReader instance');
      Object.defineProperty(reader, 'result', {
        configurable: true,
        value: 'data:image/png;base64,aGVsbG8=',
      });
      await act(async () => {
        reader.onload?.call(reader, new ProgressEvent('load') as ProgressEvent<FileReader>);
        await Promise.resolve();
      });

      expect(screen.getByAltText('pending.png')).toBeInTheDocument();
      expect(sendButton).toBeEnabled();
      fireEvent.keyDown(textarea, { key: 'Enter' });
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        text: '分析这张图片',
        attachments: [expect.objectContaining({ name: 'pending.png' })],
      }));
    } finally {
      readSpy.mockRestore();
    }
  });

  it('accepts validated in-app attachments through the composer handle', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    render(<ChatInput ref={ref} onSubmit={onSubmit} enableAttachments submitKey="enter" />);

    act(() => {
      ref.current?.appendAttachments([{
        mime: 'image/png',
        data_b64: 'aW1hZ2U=',
        size: 5,
        name: 'pdf-region.png',
      }]);
    });

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '解释选区' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith({
      text: '解释选区',
      attachments: [{
        mime: 'image/png',
        data_b64: 'aW1hZ2U=',
        size: 5,
        name: 'pdf-region.png',
      }],
      attachmentsEnabled: true,
      projectReasoningBiasEnabled: undefined,
    });
  });

  it('shows a PDF formula selection semantically while retaining its pixel payload', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    const formulaImage = {
      mime: 'image/png',
      data_b64: 'Zm9ybXVsYS1waXhlbHM=',
      size: 14,
      name: 'pdf-formula.png',
    };
    render(
      <ChatInput
        ref={ref}
        onSubmit={onSubmit}
        enableAttachments
        submitKey="enter"
        selectionContext={{
          kind: 'formula',
          page: 7,
          label: '选中的公式',
          attachmentFingerprint: chatAttachmentFingerprint(formulaImage),
        }}
      />,
    );

    act(() => {
      ref.current?.appendAttachments([formulaImage]);
    });

    const selection = screen.getByRole('group', { name: '当前 PDF 选区' });
    expect(selection).toHaveTextContent('选中的公式');
    expect(selection).toHaveTextContent('第 7 页');
    expect(screen.queryByAltText('pdf-formula.png')).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '解释这个公式' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      attachments: [formulaImage],
    }));
  });

  it('renders mixed PDF selections, hides every paired pixel payload, and removes one by id', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    const onRemoveSelectionContext = vi.fn();
    const figureImage: ChatAttachment = {
      mime: 'image/png',
      data_b64: 'ZmlndXJlLXBpeGVscw==',
      size: 13,
      name: 'pdf-figure.png',
    };
    const formulaImage: ChatAttachment = {
      mime: 'image/png',
      data_b64: 'Zm9ybXVsYS1waXhlbHM=',
      size: 14,
      name: 'pdf-formula.png',
    };
    const manualImage: ChatAttachment = {
      mime: 'image/png',
      data_b64: 'bWFudWFsLXBpeGVscw==',
      size: 13,
      name: 'manual.png',
    };

    render(
      <ChatInput
        ref={ref}
        onSubmit={onSubmit}
        enableAttachments
        submitKey="enter"
        selectionContexts={[
          {
            id: 'text-page-2',
            kind: 'text',
            page: 2,
            label: 'external text label',
            text: 'The selected paragraph links the figure and formula.',
          },
          {
            id: 'figure-page-4',
            kind: 'figure',
            page: 4,
            label: 'external figure label',
            attachmentFingerprint: chatAttachmentFingerprint(figureImage),
          },
          {
            id: 'formula-page-5',
            kind: 'formula',
            page: 5,
            label: 'external formula label',
            attachmentFingerprint: chatAttachmentFingerprint(formulaImage),
          },
        ]}
        onRemoveSelectionContext={onRemoveSelectionContext}
      />,
    );

    act(() => {
      ref.current?.appendAttachments([figureImage, formulaImage, manualImage]);
    });

    const selections = screen.getByRole('group', { name: '当前 PDF 选区' });
    expect(selections).toHaveTextContent('选中的文本');
    expect(selections).toHaveTextContent('The selected paragraph links the figure and formula.');
    expect(selections).toHaveTextContent('选中的图');
    expect(selections).toHaveTextContent('第 4 页');
    expect(selections).toHaveTextContent('选中的公式');
    expect(selections).toHaveTextContent('第 5 页');
    expect(screen.queryByAltText('pdf-figure.png')).not.toBeInTheDocument();
    expect(screen.queryByAltText('pdf-formula.png')).not.toBeInTheDocument();
    expect(screen.getByAltText('manual.png')).toBeInTheDocument();
    expect(screen.getByText('图片附件 1/4')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {
      name: '移除选区 2：选中的图，第 4 页',
    }));
    expect(onRemoveSelectionContext).toHaveBeenCalledTimes(1);
    expect(onRemoveSelectionContext).toHaveBeenCalledWith('figure-page-4');

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '一起解释这些内容' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      attachments: [formulaImage, manualImage],
    }));
  });

  it.each([
    ['figure', '选中的图'],
    ['table', '选中的表'],
    ['formula', '选中的公式'],
    ['region', '选中的区域'],
  ] as const)('ignores external labels for %s selections', (kind, expectedLabel) => {
    render(
      <ChatInput
        onSubmit={() => {}}
        selectionContext={{
          kind,
          page: 9,
          label: 'Fig. 9 screenshot-content.png',
        }}
      />,
    );

    const selection = screen.getByRole('group', { name: '当前 PDF 选区' });
    expect(selection).toHaveTextContent(expectedLabel);
    expect(selection).toHaveTextContent('第 9 页');
    expect(selection).not.toHaveTextContent('Fig. 9 screenshot-content.png');
  });

  it('clears only the paired PDF selection pixels and keeps manual image attachments', () => {
    const ref = createRef<ChatInputHandle>();
    const onClearSelectionContext = vi.fn();
    const selectionImage = {
      mime: 'image/png',
      data_b64: 'c2VsZWN0aW9u',
      size: 9,
      name: 'pdf-table.png',
    };
    const manualImage = {
      mime: 'image/png',
      data_b64: 'bWFudWFs',
      size: 6,
      name: 'manual.png',
    };
    render(
      <ChatInput
        ref={ref}
        onSubmit={() => {}}
        enableAttachments
        selectionContext={{
          kind: 'table',
          page: 4,
          label: '选中的表',
          attachmentFingerprint: chatAttachmentFingerprint(selectionImage),
        }}
        onClearSelectionContext={onClearSelectionContext}
      />,
    );

    act(() => {
      ref.current?.appendAttachments([selectionImage, manualImage]);
    });
    expect(screen.queryByAltText('pdf-table.png')).not.toBeInTheDocument();
    expect(screen.getByAltText('manual.png')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '移除选中的表' }));

    expect(onClearSelectionContext).toHaveBeenCalledTimes(1);
    expect(screen.getByAltText('manual.png')).toBeInTheDocument();
    expect(screen.queryByAltText('pdf-table.png')).not.toBeInTheDocument();
  });

  it('replaces only the paired PDF selection pixels and keeps manual image attachments', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    const priorSelectionImage = {
      mime: 'image/png',
      data_b64: 'cHJpb3Itc2VsZWN0aW9u',
      size: 15,
      name: 'pdf-figure.png',
    };
    const nextSelectionImage = {
      mime: 'image/png',
      data_b64: 'bmV4dC1zZWxlY3Rpb24=',
      size: 14,
      name: 'pdf-formula.png',
    };
    const manualImages = Array.from({ length: 5 }, (_, index) => ({
      mime: 'image/png',
      data_b64: `bWFudWFsLTI=${index}`,
      size: 8,
      name: `manual-${index + 1}.png`,
    }));
    render(
      <ChatInput
        ref={ref}
        onSubmit={onSubmit}
        enableAttachments
        submitKey="enter"
        selectionContext={{
          kind: 'formula',
          page: 8,
          label: '选中的公式',
          attachmentFingerprint: chatAttachmentFingerprint(nextSelectionImage),
        }}
      />,
    );

    act(() => {
      ref.current?.appendAttachments([priorSelectionImage, ...manualImages]);
      expect(ref.current?.replaceSelectionAttachment(
        chatAttachmentFingerprint(priorSelectionImage),
        nextSelectionImage,
      )).toBe(true);
    });

    expect(screen.getByAltText('manual-1.png')).toBeInTheDocument();
    expect(screen.getByAltText('manual-5.png')).toBeInTheDocument();
    expect(screen.queryByAltText('pdf-figure.png')).not.toBeInTheDocument();
    expect(screen.queryByAltText('pdf-formula.png')).not.toBeInTheDocument();
    expect(screen.getByText('图片附件 5/5')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '比较附件与公式' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      attachments: [...manualImages, nextSelectionImage],
    }));
  });

  it('keeps six manual images when a new PDF selection would exceed the attachment limit', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    const manualImages = Array.from({ length: 6 }, (_, index) => ({
      mime: 'image/png',
      data_b64: `bWFudWFsLTY=${index}`,
      size: 8,
      name: `manual-${index + 1}.png`,
    }));
    const selectionImage = {
      mime: 'image/png',
      data_b64: 'bmV3LXNlbGVjdGlvbg==',
      size: 13,
      name: 'pdf-figure.png',
    };
    render(<ChatInput ref={ref} onSubmit={onSubmit} enableAttachments submitKey="enter" />);

    act(() => {
      expect(ref.current?.appendAttachments(manualImages)).toBe(true);
      expect(ref.current?.replaceSelectionAttachment(undefined, selectionImage)).toBe(false);
    });

    expect(screen.getByText('⚠ 单次最多添加 6 张图片。')).toBeInTheDocument();
    expect(screen.getByAltText('manual-1.png')).toBeInTheDocument();
    expect(screen.getByAltText('manual-6.png')).toBeInTheDocument();
    expect(screen.queryByAltText('pdf-figure.png')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '分析已有附件' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ attachments: manualImages }));
  });

  it('keeps the prior PDF selection when replacement pixels are invalid', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    const priorSelectionImage = {
      mime: 'image/png',
      data_b64: 'cHJpb3Itc2VsZWN0aW9u',
      size: 15,
      name: 'pdf-table.png',
    };
    const invalidSelectionImage = {
      mime: 'image/png',
      data_b64: '',
      size: 0,
      name: 'invalid.png',
    };
    render(<ChatInput ref={ref} onSubmit={onSubmit} enableAttachments submitKey="enter" />);

    act(() => {
      expect(ref.current?.appendAttachments([priorSelectionImage])).toBe(true);
      expect(ref.current?.replaceSelectionAttachment(
        chatAttachmentFingerprint(priorSelectionImage),
        invalidSelectionImage,
      )).toBe(false);
    });

    expect(screen.getByAltText('pdf-table.png')).toBeInTheDocument();
    expect(screen.queryByAltText('invalid.png')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '解释原选区' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      attachments: [priorSelectionImage],
    }));
  });

  it('removes prior PDF selection pixels for a text selection without clearing manual images', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    const selectionImage = {
      mime: 'image/png',
      data_b64: 'c2VsZWN0aW9u',
      size: 9,
      name: 'pdf-table.png',
    };
    const manualImage = {
      mime: 'image/png',
      data_b64: 'bWFudWFs',
      size: 6,
      name: 'manual.png',
    };
    render(<ChatInput ref={ref} onSubmit={onSubmit} enableAttachments submitKey="enter" />);

    act(() => {
      ref.current?.appendAttachments([selectionImage, manualImage]);
      expect(ref.current?.replaceSelectionAttachment(
        chatAttachmentFingerprint(selectionImage),
      )).toBe(true);
    });

    expect(screen.getByAltText('manual.png')).toBeInTheDocument();
    expect(screen.queryByAltText('pdf-table.png')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '分析文本' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      attachments: [manualImage],
    }));
  });

  it('shows selected text as a bounded text preview instead of an image', () => {
    render(
      <ChatInput
        onSubmit={() => {}}
        selectionContext={{
          kind: 'text',
          page: 3,
          label: '选中的文本',
          text: 'Selected paragraph with citation [7].',
        }}
      />,
    );

    const selection = screen.getByRole('group', { name: '当前 PDF 选区' });
    expect(selection).toHaveTextContent('选中的文本');
    expect(selection).toHaveTextContent('Selected paragraph with citation [7].');
    expect(selection.querySelector('img')).toBeNull();
  });

  it('keeps attachments from consecutive imperative appends in one render turn', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    render(<ChatInput ref={ref} onSubmit={onSubmit} enableAttachments submitKey="enter" />);

    act(() => {
      expect(ref.current?.appendAttachments([{
        mime: 'image/png',
        data_b64: 'Zmlyc3Q=',
        size: 5,
        name: 'first.png',
      }])).toBe(true);
      expect(ref.current?.appendAttachments([{
        mime: 'image/png',
        data_b64: 'c2Vjb25k',
        size: 6,
        name: 'second.png',
      }])).toBe(true);
    });

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '比较两张图' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      attachments: [
        expect.objectContaining({ name: 'first.png' }),
        expect.objectContaining({ name: 'second.png' }),
      ],
    }));
  });

  it('keeps a controlled attachment draft when the composer remounts in another layout', () => {
    const manualImage: ChatAttachment = {
      mime: 'image/png',
      data_b64: 'Y29udHJvbGxlZC1tYW51YWw=',
      size: 17,
      name: 'controlled-manual.png',
    };

    function ControlledComposerHarness() {
      const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
      const [inReaderRail, setInReaderRail] = useState(false);
      const inputRef = useRef<ChatInputHandle | null>(null);

      return (
        <>
          <button type="button" onClick={() => inputRef.current?.appendAttachments([manualImage])}>
            添加手动图片
          </button>
          <button type="button" onClick={() => setInReaderRail((current) => !current)}>
            切换布局
          </button>
          <ChatInput
            key={inReaderRail ? 'reader-rail' : 'project-center'}
            ref={inputRef}
            onSubmit={() => {}}
            enableAttachments
            attachments={attachments}
            onAttachmentsChange={setAttachments}
          />
        </>
      );
    }

    render(<ControlledComposerHarness />);
    fireEvent.click(screen.getByRole('button', { name: '添加手动图片' }));
    expect(screen.getByAltText('controlled-manual.png')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '切换布局' }));
    expect(screen.getByAltText('controlled-manual.png')).toBeInTheDocument();
  });

  it('keeps a pending file read locked across remounts and merges into the latest draft', async () => {
    const onSubmit = vi.fn();
    const priorSelection: ChatAttachment = {
      mime: 'image/png',
      data_b64: 'cHJpb3Itc2VsZWN0aW9u',
      size: 15,
      name: 'prior-selection.png',
    };
    const pendingReader: { current: FileReader | null } = { current: null };
    const readSpy = vi.spyOn(FileReader.prototype, 'readAsDataURL').mockImplementation(function (
      this: FileReader,
      _blob: Blob,
    ): void {
      pendingReader.current = this;
    });

    function ControlledPendingHarness() {
      const [attachments, setAttachments] = useState<ChatAttachment[]>([priorSelection]);
      const [pendingReads, setPendingReads] = useState(0);
      const [inReaderRail, setInReaderRail] = useState(false);
      const [draft, setDraft] = useState('分析待读图片');

      return (
        <>
          <button type="button" onClick={() => setInReaderRail((current) => !current)}>
            切换布局
          </button>
          <button type="button" onClick={() => setAttachments([])}>
            移除旧选区
          </button>
          <ChatInput
            key={inReaderRail ? 'reader-rail' : 'project-center'}
            onSubmit={onSubmit}
            value={draft}
            onValueChange={setDraft}
            enableAttachments
            submitKey="enter"
            attachments={attachments}
            onAttachmentsChange={setAttachments}
            pendingAttachmentReads={pendingReads}
            onPendingAttachmentReadsChange={setPendingReads}
          />
        </>
      );
    }

    try {
      render(<ControlledPendingHarness />);
      const file = new File(['manual'], 'manual-after-remount.png', { type: 'image/png' });
      fireEvent.change(screen.getByLabelText('选择图片附件'), { target: { files: [file] } });

      expect(screen.getByRole('status', { name: '正在读取图片' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();

      fireEvent.click(screen.getByRole('button', { name: '切换布局' }));
      expect(screen.getByRole('status', { name: '正在读取图片' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();

      fireEvent.click(screen.getByRole('button', { name: '移除旧选区' }));
      expect(screen.queryByAltText('prior-selection.png')).not.toBeInTheDocument();
      fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
      expect(onSubmit).not.toHaveBeenCalled();

      const reader = pendingReader.current;
      if (!reader) throw new Error('Expected a pending FileReader instance');
      Object.defineProperty(reader, 'result', {
        configurable: true,
        value: 'data:image/png;base64,bWFudWFs',
      });
      await act(async () => {
        reader.onload?.call(reader, new ProgressEvent('load') as ProgressEvent<FileReader>);
        await Promise.resolve();
      });

      expect(screen.queryByRole('status', { name: '正在读取图片' })).not.toBeInTheDocument();
      expect(screen.queryByAltText('prior-selection.png')).not.toBeInTheDocument();
      expect(screen.getByAltText('manual-after-remount.png')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '发送' })).toBeEnabled();

      fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        text: '分析待读图片',
        attachments: [expect.objectContaining({ name: 'manual-after-remount.png' })],
      }));
    } finally {
      readSpy.mockRestore();
    }
  });

  it('explicitly rejects imperative attachment changes while disabled', () => {
    const ref = createRef<ChatInputHandle>();
    render(<ChatInput ref={ref} onSubmit={() => {}} enableAttachments disabled />);

    act(() => {
      expect(ref.current?.appendAttachments([{
        mime: 'image/png',
        data_b64: 'aW1hZ2U=',
        size: 5,
        name: 'blocked.png',
      }])).toBe(false);
      expect(ref.current?.replaceSelectionAttachment(undefined)).toBe(false);
    });

    expect(screen.getByText('⚠ 回答生成中，暂不能更换 PDF 选区。')).toBeInTheDocument();
    expect(screen.queryByAltText('blocked.png')).not.toBeInTheDocument();
  });

  it('uses a stable default question when submitting attachments without text', () => {
    const ref = createRef<ChatInputHandle>();
    const onSubmit = vi.fn();
    render(<ChatInput ref={ref} onSubmit={onSubmit} enableAttachments submitKey="enter" />);

    act(() => {
      ref.current?.appendAttachments([{
        mime: 'image/png',
        data_b64: 'aW1hZ2U=',
        size: 5,
        name: 'figure.png',
      }]);
    });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      text: '请分析这些图片。',
      attachments: [expect.objectContaining({ name: 'figure.png' })],
    }));
  });

  it('forwards the hint copy below the composer', () => {
    render(<ChatInput onSubmit={() => {}} hint="按 Ctrl/Cmd + Enter 快速发送" />);
    expect(screen.getByText('按 Ctrl/Cmd + Enter 快速发送')).toBeInTheDocument();
  });

  it('trims whitespace before submitting', () => {
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} />);
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '   ' } });
    fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(ta, { target: { value: '   trimmed   ' } });
    fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(onSubmit).toHaveBeenCalledWith({
      text: 'trimmed',
      attachments: [],
      attachmentsEnabled: false,
      projectReasoningBiasEnabled: undefined,
    });
  });
});
