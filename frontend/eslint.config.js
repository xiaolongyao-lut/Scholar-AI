import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'openapi/**',
      'out/**',
      'output/**',
      'test-results/**',
      '.cache/**',
      '.vite/**',
      'src/generated/**',
      '**/*.mjs',
      // 测试文件: .gitignore 已排除 frontend/**/*.test.{ts,tsx} + tests/ + src/test/
      // 这里同步 lint 排除, 避免本地与 CI lint 行为漂移 (任何 SDK / mock 类型噪音不阻塞主流水线)
      '**/*.test.ts',
      '**/*.test.tsx',
      'tests/**',
      'src/test/**',
    ],
  },
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parser: tseslint.parser,
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    plugins: {
      '@typescript-eslint': tseslint.plugin,
      'react-hooks': reactHooks,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      // console.error 用于致命错误, console.warn 用于降级/缺省/兜底提示,
      // console.info 用于路由级别诊断 trace; 三者都是产品里有意保留的信号粒度,
      // 不允许的是开发期遗留的 console.log / console.debug
      'no-console': ['warn', { allow: ['error', 'warn', 'info'] }],
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        destructuredArrayIgnorePattern: '^_',
      }],
    },
  },
];
