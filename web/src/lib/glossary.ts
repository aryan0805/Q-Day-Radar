// Plain-language definitions for the glossary tooltips (human tweak round 1). Each term is wrapped
// on its first use per page. `exact` is the technical term the plain wording replaces. No figures
// here: nothing in this file is a result.
export interface Term {
  plain: string;
  exact?: string;
}

export const GLOSSARY: Record<string, Term> = {
  qubit: { plain: "The unit of a quantum computer. Unlike a normal bit, it can be in a mix of 0 and 1 until it is measured." },
  shor: { plain: "A quantum method that breaks RSA and elliptic-curve encryption by finding a hidden repeating pattern.", exact: "Shor's algorithm" },
  grover: { plain: "A quantum method that finds a secret key faster than trying every key. It roughly halves the key length.", exact: "Grover's algorithm" },
  rsa: { plain: "The most common way to protect keys and signatures online. Its security rests on how hard it is to split a huge number into primes." },
  ecc: { plain: "A newer family of encryption that is shorter than RSA for the same strength. A quantum computer breaks it too.", exact: "elliptic-curve cryptography (ECC)" },
  mlkem: { plain: "A new encryption method, built to resist quantum computers, that NIST has standardised for exchanging keys.", exact: "ML-KEM (FIPS 203)" },
  transpiled: { plain: "Rewritten step by step so it runs on one particular chip. The result looks different from the original circuit.", exact: "transpiled" },
  continued: { plain: "A classic maths trick that turns a measured number into a simple fraction. Shor's method uses it to read off the repeating pattern.", exact: "continued fractions" },
  mosca: { plain: "The years to spare. It is the time until a quantum computer can break something, minus how long it must stay secret, minus how long it takes to replace.", exact: "Mosca margin" },
  crqc: { plain: "A quantum computer big and reliable enough to break real encryption.", exact: "cryptographically relevant quantum computer (CRQC)" },
  chance: { plain: "The score you would get by guessing at random. A result only means something when it is clearly above this line.", exact: "chance baseline" },
  trend: { plain: "A forecast made by drawing a line through past results and following it forward. It is an estimate, not a measurement.", exact: "trend extrapolation" },
  compiled: { plain: "A simplified demo version built for one fixed problem, with part of the answer already built in.", exact: "compiled" },
  simulator: { plain: "A normal computer that imitates a quantum computer. It is exact when perfect and inexact when it copies real noise.", exact: "simulator" },
  logical: { plain: "A reliable qubit made from many fragile physical qubits that check each other for errors.", exact: "logical qubit" },
  lattice: { plain: "A grid of points in many dimensions. Problems about it are believed to be hard even for quantum computers.", exact: "lattice cryptography" },
  toffoli: { plain: "A basic step in a quantum program. Counting these steps gives the cost of an attack.", exact: "Toffoli gate" },
};
