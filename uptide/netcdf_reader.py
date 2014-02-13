# horrible kludge to import python netcdf class - there's three different implementations to choose from!
# luckily they adhere to the same API
try:
  # this seems to be the most mature and also handles netcdf4 files
  from netCDF4 import Dataset as NetCDFFile
except ImportError:
  try:
    # this one is older but is quite often installed
    from Scientific.IO.NetCDF import NetCDFFile
  except ImportError:
    # finally, try the one in scipy that I hear conflicting things about
    try:
      # this only works in python 2.7
      from scipy.io.netcdf import NetCDFFile
    except ImportError:
      # in python 2.6 it's called something else
      from scipy.io.netcdf import netcdf_file as NetCDFFile
import numpy
import numpy.ma
import scipy.interpolate

DEFAULT_EXTRAPOLATION_LEVEL = 2

# any error generated by the NetCDFInterpolator object:
class NetCDFInterpolatorError(Exception): pass

# error caused by coordinates being out of range or inside land mask:
class CoordinateError(Exception):
  def __init__(self, message, x):
    self.message = message
    self.x = x
  def __str__(self):
    return "For coordinates x, y={}; {}".format(self.x, self.message)

class Interpolator(object):
  def __init__(self, x, y, val, mask=None, extrapolation_level = DEFAULT_EXTRAPOLATION_LEVEL):
    self.x = x
    self.y = y
    self.orig_val = val
    if mask is not None:
      self.set_mask(mask, extrapolation_level=extrapolation_level)
    else:
      self.interpolator = scipy.interpolate.RectBivariateSpline(x, y, val, kx=1, ky=1)

  def set_mask(self, mask, extrapolation_level = DEFAULT_EXTRAPOLATION_LEVEL):
    self.val_with_fill = numpy.array(self.orig_val[:])
    self.mask = numpy.array(mask[:], dtype=bool)
    self.val_with_fill[self.mask] = numpy.nan

    for n in range(extrapolation_level):
      new_mask = numpy.copy(self.mask)
      for i, j  in zip(*numpy.nonzero(self.mask)):
        # loop through neighbour values
        nb_val = []
        for ii, jj, opp in ((i,j+1,2),(i+1,j,2),(i,j-1,0),(i-1,j,1)):
          if ii<0 or jj<0 or ii>=self.val_with_fill.shape[0] or jj>=self.val_with_fill.shape[1]:
            opp_masked = opp
          elif self.mask[ii,jj]:
            opp_masked = opp
          else:
            nb_val.append(self.val_with_fill[ii,jj])

        if len(nb_val)==0:
          continue
        elif len(nb_val)==3:
          # opp_masked will be the position opposite the only one masked value
          # we leave this out, so that we linearly interpolate between the other two non-masked values
          nb_val.pop(opp_masked)

        new_mask[i,j] = False
        self.val_with_fill[i,j] = sum(nb_val)/len(nb_val)
      self.mask = new_mask

    self.interpolator = scipy.interpolate.RectBivariateSpline(self.x, self.y, self.val_with_fill, kx=1, ky=1)

  def get_val(self, x):
    if x[0]<self.x[0] or x[0]>self.x[-1] or x[1]<self.y[0] or x[1]>self.y[-1]:
      raise CoordinateError("Point outside domain", x)
    val = self.interpolator(x[0], x[1])[0,0]
    if numpy.isnan(val):
      raise CoordinateError("Point inside landmask", x)
    return val
    
class NetCDFGrid(object):
  """Implements an object to store grid information read from a NetCDF file. It can create an interpolator (see Interpolator class)
  to interpolate NetCDF fields.

  The NetCDF file should contain two coordinate fields, e.g. latitude and longitude. Each of those two coordinates
  is assumed to be aligned with one dimension of the logical 2D grid.
  To open the NetCDFGrod object:

    ncg = NetCDFGrid('foo.nc', ('nx', 'ny'), ('longitude', latitude'))

  Here 'nx' and 'ny' refer to the names of the dimensions of the logical 2D grid and 'longitude' and 'latitude' to the 
  names of the coordinate fields. The order of these should match (e.g. here, the 'nx' dimension should be the 
  dimension in which 'longitude' increases, and 'ny' the dimension in which 'latitude' increases) and determines the order
  of coordinates in arguments to method calls.
  The names of dimension and coordinate fields can be obtained by using the ncdump program of the standard NetCDF utils:
    
    $ ncdump -h foo.nc
    netcdf foo {
      dimensions:
        nx = 20 ;
        ny = 10 ;
        variables:
        double z(nx, ny) ;
        double mask(nx, ny) ;
        double longitude(nx) ;
        double latitude(ny) ;
    }

  The coordinate fields may be stored as 1d or 2d fields. For 2d coordinate fields however, it is assumed that the dimensions are
  coordinate aligned: so for example if longitude is stored as longitude(nx, ny) we assume longitude does not vary in the 
  ny direction.  The order of the dimensions and coordinate fields specified in the call does not have to match that
  of the netCDF file, i.e. we could have opened the same file with:

    nci_transpose = NetCDFInterpolator('foo.nc', ('ny', 'nx'), ('latitude', longitude'))

  The only difference would be the order of the coordinates used in subsequent method calls.
  The main method to use with this object is get_interpolator which returns an Interpolator object
  that can be called to interpolate NetCDF fields in arbitrary points:

    ip = ncg.get_interpolator('z')
    ip.get_val((lat, lon))

  The order of the coordinates given to get_val() is determined by the order of the coordinates upon creation of the ncg object.
  If many interpolations are done 
  but only within a sub-domain of the area covered by the NetCDF, it may be much more efficient to indicate the range of coordinates
  (before the call to get_interpolator()) with:

     ncg.set_ranges(((-4.0,-2.0),(58.0,59.0)))

  This will load all values within the indicated range (here -4.0<longitude<-2.0 and 58.0<latitude<59.0) in memory.
  A land-mask can be provided to avoid interpolating from undefined land-values. The mask field should be a NetCDF field that is
  1.0 in land points and 0.0 at sea.

     nci.set_mask('mask')

  Alternatively, a mask can be defined from a fill value that has been used to indicate undefined land-points. The field name
  (not necessarily the same as the interpolated field) and fill value should be provided:

     ncg.set_mask_from_fill_value('z', -9999.)

  Instead of obtaining a value, we can ask for the underlying array using get_field:

     ncg.get_field('z')

  Returns an array that stores all the values of the 'z' field. If the order of the coordinates of the field specified 
  in the NetCDF agree with that of the ncg object, a netcdf field object is returned that can be used as a numpy array. If the order
  does not match a copy is returned in a numpy array with the dimensions reordered to match that of the ncg object.

  Finally,  for the case where the coordinate fields (and optionally
  the mask field) is stored in a different file than the one containing the field values to be interpolated, the following syntax
  is provided:

    ncg1 = NetCDFInterpolator('grid.nc', ('nx', 'ny'), ('longitude', latitude'))
    ncg1.set_mask('mask')
    ncg2 = NetCDFInterpolator('values.nc', ncg1)
    ncg2.set_field('temperature')
    ncg2.get_val(...)

  Here, the coordinate information of nci, including the mask and ranges if set, are copied and used in nci2.

  """
  def __init__(self, filename, *args, **kwargs):
    self.nc = NetCDFFile(filename, 'r')

    if len(args)==1:

      # we copy the grid information of another netcdf interpolator

      nci = args[0]
      self.dimensions = nci.dimensions
      self.xy = nci.xy
      self.iranges = nci.iranges
      self.mask = nci.mask
      self.extrapolation_level = nci.extrapolation_level

    elif len(args)==2:

      dimensions = args[0]
      coordinate_fields = args[1]

      self.dimensions = dimensions
      self.xy = []

      for dimension,field_name in zip(dimensions, coordinate_fields):
        N = self.nc.dimensions[dimension]
        if not isinstance(N, int):
          # let's guess it's a netCDF4.Dimension, so we should ask for its len (yuck)
          N = len(N)
        val = self.nc.variables[field_name]
        if len(val.shape)==1:
          self.xy.append(val[:])
        elif len(val.shape)==2:
          if val.dimensions[0]==dimension:
            self.xy.append(val[:,0])
          elif val.dimensions[1]==dimension:
            self.xy.append(val[0,:])
          else:
            raise NetCDFInterpolatorError("Unrecognized dimension of coordinate field")
        else:
          raise NetCDFInterpolatorError("Unrecognized shape of coordinate field")

      self.iranges = None
      self.mask = None
      self.extrapolation_level = DEFAULT_EXTRAPOLATION_LEVEL

    self.field_name = None

    if "ranges" in kwargs:
      ranges = kwargs("ranges")
      self.set_ranges(ranges)

  def set_ranges(self, ranges):
    """Set the range of the coordinates. All the values of points located within this range are read from file at once.
    This may be more efficient if many interpolations are done within this domain."""

    if self.mask is not None:
      raise NetCDFInterpolatorError("Should set ranges before setting the mask")
    if self.iranges is not None:
      raise NetCDFInterpolatorError("Can only set ranges once")

    self.iranges = []
    for xlimits, x in zip(ranges,self.xy):
      if xlimits[0]>x[-1] or xlimits[1]<x[0]:
        raise NetCDFInterpolatorError("Specified ranges outside netcdf range")
      imin = max(numpy.argmax(x>xlimits[0])-1, 0)
      # note we take one extra because imin:imax means imin up to and including imax-1
      imax = min(numpy.argmin(x<xlimits[1])+2, len(x))
      # note that we have to cast to ints as Scientific netcdf variables don't like ranges with numpy.int64 
      self.iranges.append( (int(imin), int(imax)) )

    for i, ir in enumerate(self.iranges):
      self.xy[i] = self.xy[i][ir[0]:ir[1]]


  def get_field(self, field_name):
    """Returns the field (as netcdf variable or numpy array) given 
    by field_name. If the dimensions of the field are in different order
    than specified on creation of the NetCDFInterpolator, it will return
    a numpy array with the dimensions reordered."""
    val = self.nc.variables[field_name]

    # work out correct order of dimensions
    new_order = []; dimx = None; dimy = None
    for i, dimension in enumerate(val.dimensions):
      if dimension==self.dimensions[0]:
        dimx = i
      elif dimension==self.dimensions[1]:
        dimy = i
      else:
        new_order.append(i)

    if len(new_order)!=len(val.dimensions)-2 or dimx==None or dimy==None:
      raise NetCDFInterpolatorError("In the dimensions of the field in get_field(), both dimensions of the NetCDFGrid should occur once.")

    new_order.extend([dimx, dimy])
    if not new_order==range(len(val.dimensions)):
      val = numpy.transpose(val[:], new_order)
    if self.iranges is not None:
      ir = self.iranges
      if len(val.shape)==2:
        val = val[ir[0][0]:ir[0][1],ir[1][0]:ir[1][1]]
      elif len(val.shape)==3:
        val = val[:,ir[0][0]:ir[0][1],ir[1][0]:ir[1][1]]
      else:
        raise NetCDFInterpolatorError("NetCDF field in get_field() should be 2 or 3 dimensional")

    return val

  def set_mask(self, field_name, extrapolation_level=DEFAULT_EXTRAPOLATION_LEVEL):
    """Sets a land mask from a mask field. This field should have a value of 0.0 for land points and 1.0 for the sea"""
    """Set the name of the field to be interpolated."""
    self.mask = self.get_field(field_name)
    self.extrapolation_level =  extrapolation_level

  def set_mask_from_fill_value(self, field_name, fill_value, extrapolation_level=DEFAULT_EXTRAPOLATION_LEVEL):
    """Sets a land mask, where all points for which the supplied field equals the supplied fill value. The supplied field_name
    does not have to be the same as the field name that will be given to get_interpolator()."""
    val = self.get_field(field_name)
    self.mask = numpy.where(val[:]==fill_value,1.,0.)
    self.extrapolation_level =  extrapolation_level

  def get_interpolator(self, field_name):
    """Return an Interpolator object that interpolates a field in an arbitrary point. For example:
       ip = ncg.get_interpolator(field_name='z')
       y = ip.get_val((0.0,1.0))
    The order of the coordinates in the get_val() calls should be the same as specified when creating the ncg object."""
    val = self.get_field(field_name)
    return self.get_interpolator_from_array(val)

  def get_interpolator_from_array(self, field):
    """Same as get_interpolator(), but instead of reading a field from the NetCDF file the field is interpolated from
    the supplied array. This array should be in the same shape as an array returned from get_field. This can be used
    to first do computations on the grid *before* interpolating. Example:
       amp = ncg.get_field('amplitude')
       pha = ncg.get_field('phase')
       field = amp*numpy.cos(pha) # computes the real component of the complex number given by amp and phase
       ip = ncg.get_interpolator_from_array(field)
       y = ip.get_val((0.0,1.0))
    """
    interpolator = Interpolator(self.xy[0], self.xy[1], field,
          mask=self.mask, extrapolation_level=self.extrapolation_level)
    return interpolator
