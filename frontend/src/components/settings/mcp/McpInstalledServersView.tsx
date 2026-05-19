/**
 * Installed MCP servers view (S4a stub / plan 2026-05-20 §A4).
 *
 * In S4a this is a thin placeholder. The legacy `McpServersSection`
 * (under 高级 tab) still owns the full CRUD listing during the transition.
 * S4c migrates the listing here once install/approval state flows are
 * driven by the new installer router.
 */

export function McpInstalledServersView(): JSX.Element {
  return (
    <div className="space-y-3">
      <p className="font-label text-[11px] text-foreground/55">
        已安装的 MCP 服务器。S4a 暂以「高级」tab 的传统列表为准；S4c 会在此处接入新的安装记录、撤销授权、删除入口。
      </p>
      <div className="rounded-md border border-dashed border-outline-variant p-4 font-label text-[11px] text-foreground/40 text-center">
        S4a stub · 详细列表在「高级」tab 仍可用。
      </div>
    </div>
  );
}

export default McpInstalledServersView;
