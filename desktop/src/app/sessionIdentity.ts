const sourceIds = new WeakMap<object, number>()
let nextSourceId = 1

export function sessionSourceId(source: object): number {
  let id = sourceIds.get(source)
  if (!id) { id = nextSourceId++; sourceIds.set(source, id) }
  return id
}
