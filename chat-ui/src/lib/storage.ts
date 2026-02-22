"use client";

import type { ProviderId } from "./types";

const KEY = "plugops_chatui_settings_v1";

export type UiSettings = {
  provider: ProviderId;
  model: string;
  voiceEnabled: boolean;
  ttsEnabled: boolean;
  sttMode: "off" | "push" | "toggle";
};

export const defaultSettings: UiSettings = {
  provider: "local",
  model: "",
  voiceEnabled: false,
  ttsEnabled: true,
  sttMode: "toggle"
};

export function loadSettings(): UiSettings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return defaultSettings;
    const parsed = JSON.parse(raw) as Partial<UiSettings>;
    return { ...defaultSettings, ...parsed };
  } catch {
    return defaultSettings;
  }
}

export function saveSettings(next: UiSettings) {
  localStorage.setItem(KEY, JSON.stringify(next));
}
