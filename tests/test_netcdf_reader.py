import unittest
from uptide.netcdf_reader import NetCDFGrid, CoordinateError, NetCDFFile
import itertools
import os
import numpy

# function used to fill the netcdf field, has to be linear
def f(lat, lon):
  return lat*10 + lon

test_file_name1='tests/test_netcdf_reader1.nc'
test_file_name2='tests/test_netcdf_reader2.nc'
test_file_name3='tests/test_netcdf_reader3.nc'

def _add_field_and_mask(nc, zval):
    nc.createVariable('z', 'float64', ('lat','lon'))
    nc.variables['z'][:,:] = zval
    nc.createVariable('mask', 'float64', ('lat','lon'))
    mask = numpy.ones((10,10),dtype='float64')
    mask[3:,:] = 0.0
    nc.variables['mask'][:,:] = mask
    nc.createVariable('transposed_mask', 'float64', ('lon','lat'))
    nc.variables['transposed_mask'][:,:] = mask.T

class TestNetCDFGrid(unittest.TestCase):
  """Tests the uptide.netcdf.NetCDFGrid class"""
  @classmethod
  def setUpClass(cls):
    # it seems that many scipy installations are broken for
    # netcdf writing - therefore simply committing the
    # test files instead of writing them out on the fly here
    return
    zval = numpy.array(
        [[f(lat,lon) for lon in numpy.arange(10.0)]
                     for lat in numpy.arange(10.0)])
    nc = NetCDFFile(test_file_name1, 'w')
    nc.createDimension('lat', 10)
    nc.createDimension('lon', 10)
    nc.createVariable('latitude', 'float64', ('lat',))
    nc.createVariable('longitude', 'float64', ('lon',))
    nc.variables['latitude'][:] = numpy.arange(10.0)
    nc.variables['longitude'][:] = numpy.arange(10.0)
    _add_field_and_mask(nc, zval)
    nc.close()
    # same thing but without the coordinate fields and mask
    nc = NetCDFFile(test_file_name2, 'w')
    nc.createDimension('lat', 10)
    nc.createDimension('lon', 10)
    nc.createVariable('z', 'float64', ('lat','lon'))
    nc.variables['z'][:,:] = zval
    nc.close()
    # a version with 2d lat and lon fields
    nc = NetCDFFile(test_file_name3, 'w')
    nc.createDimension('lat', 10)
    nc.createDimension('lon', 10)
    nc.createVariable('latitude', 'float64', ('lon', 'lat')) # let's have a bit of fun and swap lon and lat
    nc.createVariable('longitude', 'float64', ('lat','lon'))
    nc.variables['latitude'][:] = numpy.tile(numpy.arange(10.0), (10,1))
    nc.variables['longitude'][:] = numpy.tile(numpy.arange(10.0), (10,1))
    _add_field_and_mask(nc, zval)
    nc.close()

  @classmethod
  def tearDownClass(self):
    # don't remove them either (see above) 
    return
    os.remove(test_file_name1)
    os.remove(test_file_name2)
    os.remove(test_file_name3)

  def _test_prepared_ncg(self, ncg, comb, coordinate_perm):
    interpolator = ncg.get_interpolator(field_name='z')
    # first the tests common to all combinations
    # point that is always inside:
    xy = [[4.33, 5.2][i] for i in coordinate_perm]
    self.assertAlmostEqual(interpolator.get_val(xy), f(4.33, 5.2))
    # point outside the domain, should raise exception:
    xy = [[-4.95, 8.3][i] for i in coordinate_perm]
    self.assertRaises(CoordinateError, interpolator.get_val, xy)

    if set(comb).intersection(('mask','transposed_mask','mask_from_fill_value')):
      # point between row of land and of sea points, should extrapolate from nearest sea row:
      xy = [[1.2, 8.3][i] for i in coordinate_perm]
      self.assertAlmostEqual(interpolator.get_val(xy), f(3.0,8.3))
      # point inside the first two land rows, should raise exception
      xy = [[0.95, 8.3][i] for i in coordinate_perm]
      self.assertRaises(CoordinateError, interpolator.get_val, xy)
    if 'ranges' in comb:
      # test within the range
      xy = [[3.0, 7.0][i] for i in coordinate_perm]
      self.assertAlmostEqual(interpolator.get_val(xy), f(3.0,7.))
      # tests outside the range, should raise exception
      xy = [[3.2, 0.9][i] for i in coordinate_perm]
      self.assertRaises(CoordinateError, interpolator.get_val, xy)
      xy = [[5.9, 9.0][i] for i in coordinate_perm]
      self.assertRaises(CoordinateError, interpolator.get_val, xy)

  # test a specific permutation of the calling sequence set_mask, set_ranges
  # and specific coordinate_perm (lat,lon) or (lon,lat)
  def _test_combination(self, comb, coordinate_perm):
    self._test_combination_file(comb, coordinate_perm, test_file_name1, test_file_name2)
    # same test but now using test .nc file 3 that has 2d coordinate fields
    self._test_combination_file(comb, coordinate_perm, test_file_name3, test_file_name2)
  
  def _test_combination_file(self, comb, coordinate_perm, grid_file_name, field_only_file_name):
    # load the netcdf created in setup()
    if coordinate_perm==(0,1):
      ncg = NetCDFGrid(grid_file_name, ('lat', 'lon'), ('latitude', 'longitude'))
    else:
      ncg = NetCDFGrid(grid_file_name, ('lon', 'lat'), ('longitude', 'latitude'))

    # call the methods specified in comb - need to call set_ranges first
    if 'ranges' in comb:
      if coordinate_perm==(0,1):
        ncg.set_ranges(((0.,4.),(2.,8.)))
      else:
        ncg.set_ranges(((2.,8.),(0.,4.)))
    if 'mask' in comb:
      ncg.set_mask('mask')
    if 'transposed_mask' in comb:
      ncg.set_mask('transposed_mask')
    if 'mask_from_fill_value' in comb:
      ncg.set_mask_from_fill_value('mask', 1.0)

    # first test interpolating a field stored on the same netcdf file
    self._test_prepared_ncg(ncg, comb, coordinate_perm)

    # now try the same for the case where the field values are stored in a separate file
    ncg2 = NetCDFGrid(field_only_file_name, ncg)
    self._test_prepared_ncg(ncg2, comb, coordinate_perm)


  # test all combinations of the calling sequence set_mask, set_ranges
  # including all combinations that only call 1 or 2 of these methods
  # also try out coordinate permutations lat,lon and lon,lat (the read nc file is lat,lon in both cases)
  def test_all_combinations(self):
    for n in range(0,3):
      for comb in itertools.combinations(['ranges', 'mask'], n):
        for coordinate_perm in ((0,1), (1,0)):
          self._test_combination(comb, coordinate_perm)

  def test_all_combinations_with_fill_value(self):
    for n in range(0,3):
      for comb in itertools.combinations(['ranges', 'mask_from_fill_value'], n):
        for coordinate_perm in ((0,1), (1,0)):
          self._test_combination(comb, coordinate_perm)

  def test_all_combinations_with_transposed_mask(self):
    for n in range(0,3):
      for comb in itertools.combinations(['ranges', 'transposed_mask'], n):
        for coordinate_perm in ((0,1), (1,0)):
          self._test_combination(comb, coordinate_perm)

if __name__ == '__main__':
      unittest.main()
