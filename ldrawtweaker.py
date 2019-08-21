import sys, collections, argparse

# ISSUE: rotation breaks the norm operation. (0..v) can become (-v..0)

def get_parser():
	def parse_axislist(value):
		"""
		Maps an axis list to indices between 0 and 2.
		Args:
			value: An axis descriptor expression.
		Raises: argparse.ArgumentTypeError if value contains anythin other than xyz
		"""
		if not all(ch in "xyz" for ch in value):
			raise argparse.ArgumentTypeError("Argument should have only xyz characters.")
		index = {"x":0, "y":1, "z":2}
		return [index[ch] for ch in value]

	def parse_swap(value):
		"""Maps an axis permutation to indices between 0 and 2."""
		values = parse_axislist(value)
		if sorted(values) != [0,1,2]:
			raise argparse.ArgumentTypeError("Argument should be a permutation of xyz.")
		return values
		
	def parse_flip(value):
		"""Maps an axis list to indices between 0 and 2."""
		values = parse_axislist(value)
		return list(set(values))

	def parse_rotate(value):
		if not all(ch in "xyz" for ch in value):
			raise argparse.ArgumentTypeError("Argument should have only xyz characters.")
		index = {"x":ROT_CW_X, "y":ROT_CW_Y, "z":ROT_CW_Z}
		return [index[ch] for ch in value]

	parser = argparse.ArgumentParser(description='analyze an LDraw file, and perform flip/swap operations on it.')
	parser.add_argument('input', help="input file name")
	parser.add_argument('--rotate', type=parse_rotate, help="a list of cw rotations around the three axes (xyz)")
	parser.add_argument('--norm', action='store_true', help="normalize coordinates to be in range [0..v]")
	parser.add_argument('--swap', type=parse_swap, help="swap axes based on this permutation")
	parser.add_argument('--flip', type=parse_flip, help="flip axes specified by argument")
	parser.add_argument('--out', help="output file name")
	parser.add_argument('--flipface', action='store_true', help="change direction of the polygons. changes between cw and ccw enumeration of a polygons points")
	# TODO(vhermecz) add round coordinate values
	return parser

def float_or_int(value):
	value = float(value)
	if abs(value-int(value)) < 1e-8:
		pass #value = int(value)
	return value

ROT_CW_X = (
	(1, 0, 0),
	(0, 0, 1),
	(0, -1, 0),
)

ROT_CW_Y = (
	(0, 0, -1),
	(0, 1, 0),
	(1, 0, 0),
)

ROT_CW_Z = (
	(0, 1, 0),
	(-1, 0, 0),
	(0, 0, 1),
)

def vector_rotate(point, matrix):
	"""
	Args:
		point: A tuple of 3
		matrix: list of rows, 3x3.
	"""
	return [
		point[0]*matrix[0][0] + point[1]*matrix[1][0] + point[2]*matrix[2][0],
		point[0]*matrix[0][1] + point[1]*matrix[1][1] + point[2]*matrix[2][1],
		point[0]*matrix[0][2] + point[1]*matrix[1][2] + point[2]*matrix[2][2],
	]

class DatFileProcessor(object):
	def __init__(self, fname):
		self.fname = fname
		self.counter = collections.defaultdict(int)
		self.out = None

	def write_output(self, line):
		if self.out:
			self.out.write(line + "\n")

	def process_raw_line(self, content):
		"""Line with unknown of invalid line type"""
		self.write_output(content)

	def process_comment(self, content):
		"""Line with line type 0"""
		self.write_output(content)

	def process_include(self, content):
		"""Line with line type 1"""
		self.write_output(content)

	def process_shape(self, linetype, color, coordinates):
		"""Line with line type 2,3,4,5"""
		content = "{0} {1} ".format(linetype,color) + " ".join(map(str, coordinates))
		self.write_output(content)

	def process(self):
		with open(self.fname) as fp:
			for line in fp:
				line = line.rstrip('\r\n')
				linetype = -1
				lineitems = line.strip().split()
				try:
					linetype = int(lineitems[0])
				except:
					self.process_raw_line(line)
					continue
				self.counter[linetype] += 1
				if 0 == linetype:
					self.process_comment(line)
				elif 1 == linetype:
					self.process_include(line)
				elif 2 <= linetype <= 5:
					try:
						color = int(lineitems[1])
						coordinates = map(float_or_int, lineitems[2:])
					except:
						self.process_raw_line(line)
						continue
					self.process_shape(linetype, color, coordinates)
				else:
					self.process_raw_line(line)

class StatReaderProcessor(DatFileProcessor):
	def __init__(self, fname):
		super(StatReaderProcessor, self).__init__(fname)
		self.limits = [
			[sys.maxint, -sys.maxint-1],
			[sys.maxint, -sys.maxint-1],
			[sys.maxint, -sys.maxint-1],
		]

	def process_shape(self, linetpye, color, coordinates):
		for i in range(3):
			for coordinate in coordinates[i:len(coordinates):3]:
				self.limits[i][0] = min(coordinate, self.limits[i][0])
				self.limits[i][1] = max(coordinate, self.limits[i][1])

	def process(self):
		super(StatReaderProcessor, self).process()
		return self.counter, self.limits

class TransformProcessor(DatFileProcessor):
	def __init__(self, fname, limits, args):
		super(TransformProcessor, self).__init__(fname)
		self.limits = limits
		self.args = args

	def donorm(self, point, limits):
		for i in range(len(point)):
			point[i] = point[i] - limits[i][0]
		return point

	def doswap(self, point, permutation):
		return [point[axis] for axis in permutation]

	def doflip(self, point, flip, limits):
		for i in range(len(point)):
			if i in flip:
				point[i] = limits[i][0] + limits[i][1] - point[i]
		return point

	def process_shape(self, linetype, color, coordinates):
		line = "{0} {1}".format(linetype, color)
		points = []
		for i in range(len(coordinates)/3):
			point = coordinates[i*3:i*3+3]
			if self.args.flip:
				point = self.doflip(point, self.args.flip, self.limits)
			if self.args.norm:
				point = self.donorm(point, self.limits)
			if self.args.swap:
				point = self.doswap(point, self.args.swap)
			if self.args.rotate:
				# NOTE: Could precompute the final matrix to minimize computation
				for operation_matrix in self.args.rotate:
					point = vector_rotate(point, operation_matrix)
			points.append(point)
		if self.args.flipface:
			points = points[::-1]
		coordinates = [value for point in points for value in point]
		super(TransformProcessor, self).process_shape(linetype, color, coordinates)

	def process(self):
		with open(self.args.out, "w") as fout:
			self.out = fout
			super(TransformProcessor, self).process()

def main():
	args = get_parser().parse_args()
	print args
	counter, limits = StatReaderProcessor(args.input).process()
	print "Linetype counts: ", dict(counter)
	print "Axis limits: ", limits
	if args.out:
		TransformProcessor(args.input, limits, args).process()

if __name__ == "__main__":
	main()
