import process from 'node:process';
import ts from 'typescript';

/**
 * Resolve optional reference packages only for the requested integration check.
 * An integration file is a test, so it compiles with the tests' options
 * (tests/tsconfig.json, which says why they differ from src's).
 */
export function typecheckIntegration(files, extraPaths) {
  const config = ts.readConfigFile('tests/tsconfig.json', ts.sys.readFile);
  if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, '\n'));
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, `${process.cwd()}/tests`);
  const paths = { ...parsed.options.paths, ...extraPaths };
  const program = ts.createProgram(files, { ...parsed.options, paths });
  const diagnostics = [...parsed.errors, ...ts.getPreEmitDiagnostics(program)];
  if (diagnostics.length) {
    throw new Error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {
      getCanonicalFileName: name => name, getCurrentDirectory: () => process.cwd(), getNewLine: () => '\n',
    }));
  }
}
