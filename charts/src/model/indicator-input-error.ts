/**
 * A descriptor or input validator can report a condition the user can fix.
 * Calculation failures also surface on the instance's data status, allowing
 * the host to display the reason while other studies continue drawing.
 */
export class IndicatorInputError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = 'IndicatorInputError';
  }
}
