def ConvDecToBaseVar3(num, base):
    if base > 16 or base < 2:
  raise ValueError, 'The base number must be between 2 and 16.'
    dd = dict(zip(range(16), [hex(i).split('x')[1] for i in range(16)]))
    if num == 0: return ''
    num, rem = divmod(num, base)
    return ConvDecToBaseVar3(num, base)+dd[rem]
