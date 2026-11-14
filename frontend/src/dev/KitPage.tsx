// Developer-only sample page (#dev-kit): every shadcn component we ship, in one place, so the screenshot and smoke
// tools can check that the old global selectors do not leak into them.  Never reachable from the UI; the entry in
// App.tsx only loads this file when import.meta.env.DEV or VITE_DEV_KIT=1.  Copy is English on purpose (no i18n).
import { useState } from "react";
import { Bell, Check, ChevronDown, Download, ExternalLink, Info, Plus, Search, Settings, Sparkles, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { MaterialsBlock, PaletteBlock, TypeBlock, UpDownBlock } from "./TokenKit";

const VARIANTS = ["default", "secondary", "outline", "ghost", "destructive", "link"] as const;
const SIZES = ["xs", "sm", "default", "lg"] as const;
const ICONS = [Search, Plus, Settings, Trash2, ChevronDown, Check, X, Bell, Download, ExternalLink, Sparkles, Info];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3" data-kit-section={title}>
      <h2 className="text-sm font-semibold text-muted-foreground">{title}</h2>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </section>
  );
}

// Bare tags with no class: the smoke check reads their computed style to see which reset they get.
function BareTags() {
  return (
    <>
      <h2>Heading</h2>
      <p>Paragraph</p>
      <ul><li>Item</li></ul>
      <button type="button">Button</button>
      <a href="#dev-kit/probe">Link</a>
      <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true"><rect width="8" height="8" /></svg>
    </>
  );
}

// Scope probes, shown only on #dev-kit/probe.  "outside": no data-legacy above, so plain preflight must apply.
// "island": a data-legacy subtree inside a shadcn-style container (what the P2 shell does), so the old
// browser-default restore must apply even though a data-slot element sits above it.
function ScopeProbes() {
  return (
    <section className="space-y-3" data-kit-section="Scope probes">
      <h2 className="text-sm font-semibold text-muted-foreground">Scope probes</h2>
      <div data-probe="outside" className="flex flex-col items-start gap-2 text-sm"><BareTags /></div>
      <div data-slot="probe-container">
        <div data-legacy="" data-probe="island"><BareTags /></div>
      </div>
    </section>
  );
}

export default function KitPage() {
  const [checked, setChecked] = useState(true);
  const [menuFlag, setMenuFlag] = useState(true);

  return (
    <TooltipProvider>
      <main className="min-h-screen space-y-8 bg-background p-6 text-foreground" data-kit-page>
        <h1 className="text-xl font-semibold">UI kit (dev only)</h1>

        <Section title="Button variants">
          {VARIANTS.map((variant) => (
            <Button key={variant} variant={variant}>{variant}</Button>
          ))}
        </Section>

        <Section title="Button sizes">
          {SIZES.map((size) => (
            <Button key={size} size={size}>{size}</Button>
          ))}
          <Button size="icon" aria-label="Add"><Plus /></Button>
          <Button size="icon-sm" variant="outline" aria-label="Settings"><Settings /></Button>
          <Button disabled>disabled</Button>
          <Button><Download /> With icon</Button>
        </Section>

        <Section title="Dialog">
          <Dialog>
            <DialogTrigger asChild><Button variant="outline" data-kit="dialog-trigger">Open dialog</Button></DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Rename bot</DialogTitle>
                <DialogDescription>Dialogs trap focus, close on Esc and return focus to the trigger.</DialogDescription>
              </DialogHeader>
              <Input defaultValue="NewsBot" aria-label="Bot name" />
              <DialogFooter>
                <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
                <DialogClose asChild><Button>Save</Button></DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </Section>

        <Section title="Dropdown menu">
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline" data-kit="menu-trigger">Open menu <ChevronDown /></Button></DropdownMenuTrigger>
            <DropdownMenuContent className="w-48">
              <DropdownMenuLabel>Account</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem><Settings /> Settings</DropdownMenuItem>
              <DropdownMenuItem variant="destructive"><Trash2 /> Delete</DropdownMenuItem>
              <DropdownMenuCheckboxItem checked={menuFlag} onCheckedChange={setMenuFlag}>Show hints</DropdownMenuCheckboxItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </Section>

        <Section title="Select">
          <Select defaultValue="haiku">
            <SelectTrigger className="w-48" data-kit="select-trigger" aria-label="Model"><SelectValue placeholder="Model" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="haiku">haiku-5.5</SelectItem>
              <SelectItem value="ember">muse-ember</SelectItem>
              <SelectItem value="terra">gpt-6.1-terra</SelectItem>
            </SelectContent>
          </Select>
        </Section>

        <Section title="Input, checkbox, switch">
          <Input className="w-56" placeholder="Search symbol" aria-label="Search symbol" />
          <Input className="w-56" type="password" defaultValue="secret" aria-label="Password" />
          <Input className="w-56" disabled value="Disabled" aria-label="Disabled input" readOnly />
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={checked} onCheckedChange={(value) => setChecked(value === true)} aria-label="Remember me" /> Remember me
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Switch defaultChecked aria-label="Notifications" /> Notifications
          </label>
        </Section>

        <Section title="Tooltip">
          <Tooltip>
            <TooltipTrigger asChild><Button variant="outline" size="icon" data-kit="tooltip-trigger" aria-label="Help"><Info /></Button></TooltipTrigger>
            <TooltipContent>Model opinion, not a source</TooltipContent>
          </Tooltip>
        </Section>

        <Section title="Icons (lucide-react)">
          {ICONS.map((Icon, index) => <Icon key={index} className="size-5" aria-hidden />)}
        </Section>

        <PaletteBlock />
        <TypeBlock />
        <MaterialsBlock />
        <UpDownBlock />

        {window.location.hash === "#dev-kit/probe" && <ScopeProbes />}
      </main>
    </TooltipProvider>
  );
}
