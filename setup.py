from distutils.core import setup

setup(name='locker-support',
      version='1.0',
      author='Debathena Project',
      author_email='debathena@mit.edu',
      py_modules=['locker', 'athdir'],
      scripts=['attach', 'detach', 'fsid', 'quota', 'athdir'],
      )
