import crypto from "crypto";

export type StoredFile = {
  file_id: string;
  name: string;
  mime: string;
  size: number;
  path: string; // tmp path (starter only)
  createdAt: number;
};

const g = globalThis as any;
if (!g.__plugops_file_store) g.__plugops_file_store = new Map<string, StoredFile>();

export const fileStore: Map<string, StoredFile> = g.__plugops_file_store;

export function newId() {
  return crypto.randomBytes(16).toString("hex");
}
