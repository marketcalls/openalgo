// The package entry. value-b reaches it by its package name, as a tier
// reaches the base, so the runtime loop index, value-a, value-b is only
// found when the name resolves through tsconfig paths.
export { valueA } from './value-a';
export const shared = 1;
