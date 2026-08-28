/**
 * Browser entry point. Anton's own React root, mounted directly -- no plugin
 * loader, no DI container, no slot registry: the whole UI is this tree.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './anton-platform.css'
import { App } from './App.tsx'

const host = document.getElementById('root')
if (host === null) throw new Error('anton web: #root is missing from index.html')
createRoot(host).render(<StrictMode><App /></StrictMode>)
