/** `sidebar` namespace dictionaries. */

/** Simplified Chinese dictionary (the key-set source of truth). */
export const zh = {
  'session.new.label': '新建会话',
  'toggle.open': '打开侧边栏',
  'toggle.collapse': '收起侧边栏',
} as const

/** English dictionary, key-identical to the Chinese source of truth. */
export const en: Record<SidebarKey, string> = {
  'session.new.label': 'New session',
  'toggle.open': 'Open sidebar',
  'toggle.collapse': 'Collapse sidebar',
}

/** Key domain of the `sidebar` namespace (zh is the source of truth). */
export type SidebarKey = keyof typeof zh
