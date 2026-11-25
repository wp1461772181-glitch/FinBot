import type { OwnerViewVersion } from "./api/owner-views";
export function statusPhrase(status: string): string;
export function monthDay(value: string | null | undefined, timeZone?: string): { month: number; day: number } | null;
export function dayLabel(value: string | null | undefined, locale?: string): string;
export function splitVersions(versions: OwnerViewVersion[] | null | undefined): { active: OwnerViewVersion | null; earlier: OwnerViewVersion[] };
export function hasAnyView(versions: OwnerViewVersion[] | null | undefined): boolean;
export function versionSpan(version: Pick<OwnerViewVersion, "created_at" | "ended_at">, locale?: string): string;
