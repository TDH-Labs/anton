import { useEffect, useState } from 'react'
import type { HeroBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { SidebarBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-sidebar/client'

type OfficialBrandMarkProps = HeroBrandMarkOwnerProps & SidebarBrandMarkOwnerProps

export function OfficialBrandMark({ size, className }: OfficialBrandMarkProps) {
  const [isSonOfAnton, setIsSonOfAnton] = useState(false)

  useEffect(() => {
    const applyMode = (isSon: boolean) => {
      setIsSonOfAnton(isSon)
      localStorage.setItem('sonOfAntonMode', String(isSon))
      if (isSon) {
        document.body.setAttribute('data-anton-mode', 'son')
      } else {
        document.body.removeAttribute('data-anton-mode')
      }
    }
    
    // Initial check
    applyMode(localStorage.getItem('sonOfAntonMode') === 'true')

    const handleToggle = () => applyMode(localStorage.getItem('sonOfAntonMode') === 'true')
    const handlePreset = (e: any) => {
      applyMode(e.detail.id === 'son-of-anton');
      globalThis.fetch(e.detail.id === 'son-of-anton' ? '/api/mode/son-of-anton' : '/api/mode/standard', { method: 'POST' }).catch(console.error);
    }
    window.addEventListener('son-of-anton-toggle', handleToggle)
    window.addEventListener('preset-selected', handlePreset)
    return () => {
      window.removeEventListener('son-of-anton-toggle', handleToggle)
      window.removeEventListener('preset-selected', handlePreset)
    }
  }, [])

  const px = typeof size === 'number' ? size : 24
  const src = isSonOfAnton ? "/son_of_anton_logo.svg" : "/anton_logo.jpg"
  return <img src={src} className={className} style={{ width: px, height: px, borderRadius: 4, objectFit: 'cover' }} alt="Anton Logo" />
}

export function OfficialBrandName() {
  const [isSonOfAnton, setIsSonOfAnton] = useState(false)

  useEffect(() => {
    const handleToggle = () => setIsSonOfAnton(localStorage.getItem('sonOfAntonMode') === 'true')
    const handlePreset = (e: any) => setIsSonOfAnton(e.detail.id === 'son-of-anton')
    window.addEventListener('son-of-anton-toggle', handleToggle)
    window.addEventListener('preset-selected', handlePreset)
    return () => {
      window.removeEventListener('son-of-anton-toggle', handleToggle)
      window.removeEventListener('preset-selected', handlePreset)
    }
  }, [])

  return <span style={{ fontWeight: 800, fontSize: '0.92rem', letterSpacing: '-0.02em', color: 'var(--text-main)' }}>
    {isSonOfAnton ? 'SON OF ANTON' : 'ANTON'}
  </span>
}
