import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// Hard rule (gate 5): web/src reads no environment except NODE_ENV, and there is no NEXT_PUBLIC_.
const envRule = [
  "error",
  {
    selector:
      "MemberExpression[object.object.name='process'][object.property.name='env'][property.name!='NODE_ENV']",
    message: "Only process.env.NODE_ENV may be read in web/src.",
  },
  {
    selector: "MemberExpression[computed=true][object.object.name='process'][object.property.name='env']",
    message: "No computed process.env access.",
  },
  {
    selector: "VariableDeclarator > MemberExpression[object.name='process'][property.name='env']",
    message: "Do not destructure or alias process.env.",
  },
  {
    selector: "Literal[value=/NEXT_PUBLIC_/]",
    message: "NEXT_PUBLIC_ variables are not allowed.",
  },
];

const config = [
  { ignores: ["out/**", ".next/**", ".vercel/**", "node_modules/**", "next-env.d.ts"] },
  ...nextCoreWebVitals,
  ...nextTypescript,
  { files: ["src/**/*.{ts,tsx}", "next.config.ts"], rules: { "no-restricted-syntax": envRule } },
];

export default config;
