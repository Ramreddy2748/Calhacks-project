// Only explicit international numbers are candidates; never guess a country code.
export function phoneNumbersIn(text) {
  const matches = String(text || '').match(/\+[1-9](?:[ \t().-]*\d){7,14}(?![ \t().-]*\d)/g) || [];
  return [...new Set(matches.map(number => '+' + number.replace(/\D/g, '')))];
}
