// The panel of the composer's model selector (the model only: how hard to think is the model's call, question by question; the effort row
// was taken out 11-28): a centred command palette on a wide screen (AI Elements' Model Selector), a bottom drawer below 1024px, one body in both.
// A chunk of its own: ModelEffortPicker loads it when the badge is first pressed (or hovered), so the composer carries only the badge.  It owns no state that matters:
// the picker holds the catalog, the shown bot and the save, and this draws them; a choice goes back through `onChoose`.
import { useEffect, useRef, useState } from "react";
import { Check, Lightbulb, Server } from "lucide-react";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import {
  ModelSelector, ModelSelectorContent, ModelSelectorEmpty, ModelSelectorGroup, ModelSelectorInput, ModelSelectorItem, ModelSelectorList, ModelSelectorLogo,
} from "@/components/ai-elements/model-selector";
import { Command } from "@/components/ui/command";
import { cn } from "@/lib/utils";
import { useLocale } from "../../i18n";
import { modelSections } from "../../model-effort.mjs";
import type { CatalogEffortEntry, ModelGroup } from "../../model-effort.mjs";
import { useMatchMedia, PHONE_QUERY } from "./use-media";
import type { Bot, ModelCatalog } from "../../api/bots";

export type PanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog: ModelCatalog | null;
  shown: Bot;
  entry: CatalogEffortEntry | null;
  busy: boolean;
  error: string;
  onChoose: (kind: "model" | "effort", value: string | null) => void;
  /** Where focus goes when the panel closes: the badge (the dialog has no Trigger of its own to return to). */
  returnFocus: () => void;
};

const DEFAULT_VALUE = "__server-default__";
const pill = "rounded-full bg-action-soft px-1.5 text-caption text-action";

export default function ModelEffortPanel(props: PanelProps) {
  const { t } = useLocale();
  const phone = useMatchMedia(PHONE_QUERY);
  const [highlight, setHighlight] = useState(props.shown.model ?? DEFAULT_VALUE);
  // The panel stays mounted between openings (and across a switch of bot): every opening starts on the current model, never on
  // the row last hovered, so Enter right away re-picks what is shown instead of saving a stale row.
  useEffect(() => { if (props.open) setHighlight(props.shown.model ?? DEFAULT_VALUE); }, [props.open, props.shown.model]);
  const commandProps = { value: highlight, onValueChange: setHighlight, className: "bg-transparent rounded-[inherit]" };
  const title = t("模型");
  const onCloseAutoFocus = (event: Event) => { event.preventDefault(); props.returnFocus(); };
  // A wrapper that is always drawn, even while the catalog is on its way: the keyboard hint and the error sit under the list in both shells.
  const body = <PanelBody {...props} />;
  if (phone) {
    return <Drawer open={props.open} onOpenChange={props.onOpenChange}>
      <DrawerContent data-testid="model-picker" aria-describedby={undefined} className="picker-glass pb-[env(safe-area-inset-bottom,0px)]"
        onOpenAutoFocus={(event) => event.preventDefault()} onCloseAutoFocus={onCloseAutoFocus}>
        <DrawerTitle className="sr-only">{title}</DrawerTitle>
        <Command {...commandProps} className={cn("min-h-0", commandProps.className)}>{body}</Command>
      </DrawerContent>
    </Drawer>;
  }
  return <ModelSelector open={props.open} onOpenChange={props.onOpenChange}>
    <ModelSelectorContent title={title} data-testid="model-picker" showCloseButton={false} aria-describedby={undefined} onCloseAutoFocus={onCloseAutoFocus}
      className="picker-glass gap-0 overflow-hidden rounded-lg sm:max-w-[28rem]" commandProps={commandProps}>
      {body}
    </ModelSelectorContent>
  </ModelSelector>;
}

function PanelBody({ catalog, shown, busy, error, onChoose }: PanelProps) {
  const { t } = useLocale();
  const list = useRef<HTMLDivElement>(null);
  const sections = catalog ? modelSections(catalog, shown.model) : null;
  // The list opens on the current model, in view even when the catalog is long.
  useEffect(() => { list.current?.querySelector("[data-checked=true]")?.scrollIntoView({ block: "nearest" }); }, [Boolean(catalog)]); // eslint-disable-line react-hooks/exhaustive-deps

  return <>
    <ModelSelectorInput placeholder={t("搜索模型或服务商…")} aria-label={t("模型")} />
    <ModelSelectorList ref={list} label={t("模型")} className="max-h-[min(20rem,42dvh)] px-1.5 py-1">
      {!sections && !error && <p className="px-2 py-3 text-small text-muted-foreground">{t("正在读取模型目录…")}</p>}
      <ModelSelectorEmpty className="py-6 text-center text-small text-muted-foreground">{t("没有匹配的模型")}</ModelSelectorEmpty>
      {sections && <>
        <ModelSelectorGroup>
          <ModelSelectorItem value={DEFAULT_VALUE} keywords={[t("服务器默认模型"), sections.defaultChoice.defaultName ?? ""]} disabled={busy} data-checked={sections.defaultChoice.checked}
            onSelect={() => onChoose("model", null)} className={rowClass}>
            <span className="picker-tile"><Server className="size-3.5 text-muted-foreground" aria-hidden="true" /></span>
            <span className="min-w-0 flex-1 truncate text-body font-medium text-ink">{t("服务器默认模型")}{sections.defaultChoice.defaultName ? ` (${sections.defaultChoice.defaultName})` : ""}</span>
            {sections.defaultChoice.checked && <Check className="size-4 shrink-0 text-brand" aria-hidden="true" />}
          </ModelSelectorItem>
        </ModelSelectorGroup>
        {sections.groups.map((group) => <ModelSelectorGroup key={group.provider || "other"} heading={<GroupHeading group={group} />}>
          {group.items.map((row) => <ModelSelectorItem key={row.value} value={row.value} keywords={[row.name, row.model, group.label ?? group.provider]} disabled={busy}
            data-checked={row.checked} onSelect={() => onChoose("model", row.value)} className={rowClass}>
            <span className="picker-tile"><ModelSelectorLogo provider={row.logo} className="size-[15px]" /></span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-body font-medium leading-[18px] text-ink">{row.name}</span>
              <span className="flex items-center gap-1.5 text-caption leading-4 text-faint">
                <span className="truncate">{row.model}</span>
                {row.thinking && <Lightbulb className="size-3 shrink-0" aria-label={t("支持思考")} />}
              </span>
            </span>
            {row.keyMissing && <small className={pill}>{t("缺 key")}</small>}
            {row.checked && <Check className="size-4 shrink-0 text-brand" aria-hidden="true" />}
          </ModelSelectorItem>)}
        </ModelSelectorGroup>)}
      </>}
    </ModelSelectorList>
    <div className="border-t border-line px-4 pb-3 pt-2.5">
      <p data-testid="effort-note" className="pb-1 text-caption text-muted-foreground">{t("思考深度不用选：它按每个问题自己决定，从浅到深。")}</p>
      {error && <p role="alert" className="pb-1 text-small text-danger">{error}</p>}
      <p className="text-caption text-muted-foreground">{t("模型和 key 只在服务器上，浏览器不保存 key。")}</p>
      <p className="mt-1 hidden text-caption text-faint lg:block" aria-hidden="true">{t("↑↓ 选择　↵ 确认")}</p>
    </div>
  </>;
}

const rowClass = "picker-row gap-2.5 rounded-md px-2 py-2 text-body";

function GroupHeading({ group }: { group: ModelGroup }) {
  const { t } = useLocale();
  const label = group.label ?? (group.provider === "custom" ? t("自定义（OpenAI 兼容）") : t("其他服务商"));
  return <span className="flex items-center gap-1.5"><ModelSelectorLogo provider={group.logo} className="size-3 opacity-70" />{label}</span>;
}
