// Minimal JSON Schema validator for the subset the action schemas use (type, properties, required,
// enum, items, minimum, additionalProperties: false). The same schemas are published over MCP.
export function validate(schema, value, at = 'args') {
  const errors = [];
  const type = schema.type;
  const typeOk = {
    object: (v) => v !== null && typeof v === 'object' && !Array.isArray(v),
    array: Array.isArray,
    string: (v) => typeof v === 'string',
    integer: Number.isInteger,
    number: (v) => typeof v === 'number' && Number.isFinite(v),
    boolean: (v) => typeof v === 'boolean',
  };
  if (type && !typeOk[type](value)) return [`${at} must be ${type}`];
  if (schema.enum && !schema.enum.includes(value)) errors.push(`${at} must be one of ${schema.enum.join(', ')}`);
  if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${at} must be >= ${schema.minimum}`);
  if (schema.minLength !== undefined && value.length < schema.minLength) errors.push(`${at} must not be empty`);
  if (type === 'array' && schema.minItems !== undefined && value.length < schema.minItems) errors.push(`${at} needs at least ${schema.minItems} item(s)`);
  if (type === 'array' && schema.items) value.forEach((v, i) => errors.push(...validate(schema.items, v, `${at}[${i}]`)));
  if (type === 'object') {
    for (const key of schema.required || []) if (value[key] === undefined) errors.push(`${at}.${key} is required`);
    for (const [key, v] of Object.entries(value)) {
      const sub = schema.properties?.[key];
      if (sub) errors.push(...validate(sub, v, `${at}.${key}`));
      else if (schema.additionalProperties === false) errors.push(`${at}.${key} is not a known parameter`);
    }
  }
  return errors;
}
