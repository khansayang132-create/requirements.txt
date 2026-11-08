function add(a: number, b: number): number {
  return a + b;
}
const s: string = add(1, 2); // intentional type error
console.log(s);
