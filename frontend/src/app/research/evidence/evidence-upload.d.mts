export declare const TITLE_MAX: number;
export declare const REASON_MAX: number;
export declare const FILE_ACCEPT: string;
export declare const IMPACTS: ReadonlyArray<"low" | "medium" | "high">;
export type UploadField = "file" | "title" | "sourceUrl" | "publishedAt" | "reason";
export type UploadErrors = Partial<Record<UploadField, "missing" | "type" | "not-https">>;
export type UploadForm = { file: { name: string; type: string } | null; title: string; sourceUrl: string; publishedAt: string; reason: string };
export declare function isHttpsUrl(value: string): boolean;
export declare function isAllowedEvidenceFile(file: { name: string; type: string }): boolean;
export declare function validateUpload(form: UploadForm): UploadErrors;
export declare function uploadInput(form: { file: File; title: string; sourceUrl: string; publishedAt: string; stars: number; impact: "low" | "medium" | "high"; reason: string }): {
  file: File; title: string; sourceUrl: string; publishedAt: string; credibilityStars: number; credibilityReason: string; impactSeverity: "low" | "medium" | "high";
};
export declare const FIELD_ORDER: ReadonlyArray<UploadField>;
export declare function firstInvalid(errors: UploadErrors): UploadField | null;
