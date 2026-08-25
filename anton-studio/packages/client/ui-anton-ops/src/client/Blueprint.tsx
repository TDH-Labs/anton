import type { CSSProperties, ReactNode } from 'react'
import css from './blueprint.module.css'

/**
 * Blueprint-framed card: 1px hairline border plus four 11x11 "+" registration
 * marks offset -6px at the corners (README, "Screens / Views" — "Blueprint
 * frame"). Wraps any major card so every screen gets the same treatment
 * instead of hand-rolled corner spans.
 */
export function Blueprint(props: { children?: ReactNode; style?: CSSProperties; className?: string }) {
  const className = props.className === undefined ? css.blueprint : `${css.blueprint} ${props.className}`
  return (
    <div className={className} style={props.style}>
      <span className={`${css.corner} ${css.cornerTl}`} />
      <span className={`${css.corner} ${css.cornerTr}`} />
      <span className={`${css.corner} ${css.cornerBl}`} />
      <span className={`${css.corner} ${css.cornerBr}`} />
      {props.children}
    </div>
  )
}
