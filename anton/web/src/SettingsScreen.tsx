import bp from './blueprint.module.css'
import { N8nSettingsSection } from './N8nSettingsSection.tsx'

const LN = '1px solid var(--dsw-alias-border-l2)'

/**
 * Settings: the deployment-level configuration Anton owns itself.
 *
 * Model/provider keys are not here -- they live in the setup wizard and the
 * Add-ons screen, which already own credential entry and its masking rules.
 */
export function SettingsScreen() {
  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', padding: '18px 26px 14px', borderBottom: LN }}>
        <div className={bp.kicker}>DEPLOYMENT CONFIGURATION</div>
        <div className={bp.screenTitle}>Settings</div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <N8nSettingsSection />
      </div>
    </div>
  )
}
