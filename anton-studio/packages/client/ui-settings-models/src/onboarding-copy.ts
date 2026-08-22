/** Durable settings namespace for product-wide GUI onboarding facts. */
export const WELCOME_NOTICE_SETTINGS_NAMESPACE = 'ui-onboarding'

/** Field storing the last welcome notice version the user acknowledged. */
export const WELCOME_NOTICE_ACK_FIELD = 'welcomeNoticeVersion'

/**
 * Bump only when the notice changes materially and every user should see it
 * again. The acknowledgement is compared for exact equality.
 */
export const WELCOME_NOTICE_VERSION = '2026-08-20.1'

/** The complete editable internal-testing notice in both supported GUI locales. */
export const WELCOME_NOTICE_COPY = {
  zh: {
    title: '在 Anton 开始工作之前',
    body: 'Anton 是全新的软件：它会起草自动化、运行计划任务，并对你连接的系统采取真实操作。在建立信任之前，请在"记忆"中检查它早期的运行结果，并对涉及资金、凭证或生产环境的操作保留人工审批。\n\n默认情况下不会有任何操作在无人监督下运行——所有有实际影响的自动化都会在"等待你决定"中等待你批准一次，或者由你告诉 Anton 不必再询问。',
    continueLabel: '继续',
  },
  en: {
    title: 'Before Anton gets to work',
    body: 'Anton is new software: it drafts automations, runs scheduled jobs, and can take real actions on the systems you connect. Check its early runs in Memory, and keep sign-off on for anything that touches money, credentials, or production until you trust its judgment.\n\nNothing runs unsupervised by default — every automation with real consequences waits for you in Waiting on you until you approve it once, or tell Anton to stop asking.',
    continueLabel: 'Continue',
  },
} as const
