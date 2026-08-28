/** CSS Modules imported by the Ops Center screens; Vite resolves these at
 *  build time, TypeScript needs the shape declared. */
declare module '*.module.css' {
  const classes: Record<string, string>
  export default classes
}
declare module '*.css' {}
